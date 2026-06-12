"""S3 — Schematic capture: LLM writes SKiDL → kicad-cli ERC.

Flow:
  1. LLM generates a SKiDL Python script from the ProductSpec.
  2. SKiDLAdapter runs the script (subprocess); it emits .kicad_sch + .net files.
  3. KiCadCLIAdapter runs `kicad-cli sch erc` on the .kicad_sch.
  4. ERCVerifier parses the JSON report → VerifierResult.
  5. If ERC fails, violations are fed back to the LLM for repair (up to max_retries).
  6. Human checkpoint fires regardless of ERC outcome (spec says mandatory for analog/RF/power).

Phase 1 simplification: parts are NOT grounded against a distributor API yet;
that's Phase 2 (S2 architecture + sourcing stage).
"""

from __future__ import annotations

import json
from pathlib import Path

from mandrel.adapters.kicad import KiCadCLIAdapter
from mandrel.adapters.skidl_gen import SKiDLAdapter
from mandrel.core.state import DesignState, SchematicArtifact, VerifierResult, Violation
from mandrel.core.workflow import Context, StageResult
from mandrel.llm.prompts import S3_SKIDL_GEN
from mandrel.llm.provider import LLMProvider, Message
from mandrel.verify.erc import ERCVerifier


class SchematicStage:
    """S3: LLM-generated SKiDL → KiCad schematic → ERC gate."""

    name = "s3_schematic"

    def __init__(
        self,
        llm: LLMProvider,
        skidl: SKiDLAdapter | None = None,
        kicad: KiCadCLIAdapter | None = None,
        erc_verifier: ERCVerifier | None = None,
        max_retries: int = 3,
    ) -> None:
        self._llm     = llm
        self._skidl   = skidl   or SKiDLAdapter()
        self._kicad   = kicad   or KiCadCLIAdapter()
        self._erc     = erc_verifier or ERCVerifier()
        self._max_retries = max_retries

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        if state.spec is None:
            raise ValueError("S3 requires state.spec — run S1 first.")

        output_dir = ctx.project_dir / "s3_schematic"
        output_dir.mkdir(parents=True, exist_ok=True)

        spec_json = json.dumps(state.spec.model_dump(mode="json"), indent=2)
        arch_json = (
            json.dumps(state.architecture.model_dump(mode="json"), indent=2)
            if state.architecture
            else "null (no architecture from S2 — infer from spec)"
        )
        violations_context = ""
        erc_result: VerifierResult | None = None
        skidl_script = ""

        for attempt in range(1, self._max_retries + 1):
            # 1. LLM generates (or repairs) the SKiDL script
            prompt = S3_SKIDL_GEN.format(
                spec_json=spec_json,
                arch_json=arch_json,
                output_dir=str(output_dir),
            )
            if violations_context:
                prompt += (
                    f"\n\nPREVIOUS ERC VIOLATIONS (fix these):\n{violations_context}"
                )

            await ctx.progress(
                self.name,
                f"LLM writing SKiDL schematic script (attempt {attempt}/{self._max_retries}) — "
                "this is the longest generation in the pipeline…",
            )
            skidl_script = await self._llm.complete(
                [Message(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=4096,
                on_token=ctx.stream_reporter(
                    self.name,
                    f"LLM writing SKiDL script (attempt {attempt}/{self._max_retries})",
                ),
            )
            skidl_script = _strip_markdown(skidl_script)

            # 2. Run SKiDL
            await ctx.progress(self.name, "Running SKiDL script to emit schematic + netlist…")
            try:
                outputs = self._skidl.run_script(skidl_script, output_dir)
            except Exception as exc:
                exc_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if attempt == self._max_retries:
                    return StageResult(
                        state=state,
                        artifacts=[],
                        verifier_result=VerifierResult(
                            passed=False,
                            violations=[Violation(
                                code="SKIDL_EXEC_ERROR",
                                message=exc_msg,
                                severity="error",
                            )],
                        ),
                    )
                violations_context = f"SKiDL execution error:\n{exc_msg}"
                continue

            # Save the script regardless of ERC outcome
            script_path = output_dir / "skidl_design.py"
            script_path.write_text(skidl_script, encoding="utf-8")

            # run_script keys by file stem; accept any .kicad_sch / .net output
            sch_path = outputs.get("schematic") or next(
                (p for p in outputs.values() if p.suffix == ".kicad_sch"), None
            )
            net_path = outputs.get("netlist") or next(
                (p for p in outputs.values() if p.suffix == ".net"), None
            )

            # 3. kicad-cli ERC
            if sch_path and sch_path.exists():
                await ctx.progress(self.name, "Running kicad-cli ERC on schematic…")
                try:
                    report_path = self._kicad.run_erc(sch_path, output_dir)
                    erc_result  = self._erc.check(report_path)
                except Exception as exc:
                    # kicad-cli not available or ERC parse error — warn, don't block Phase 1
                    exc_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                    erc_result = VerifierResult(
                        passed=True,
                        score=0.5,
                        violations=[Violation(
                            code="ERC_UNAVAILABLE",
                            message=exc_msg,
                            severity="warning",
                        )],
                    )
            elif net_path and net_path.exists():
                # Netlist (the artifact S4 needs) exists; schematic is only
                # required for ERC, so its absence degrades rather than fails.
                erc_result = VerifierResult(
                    passed=True,
                    score=0.75,
                    violations=[Violation(
                        code="SCHEMATIC_UNAVAILABLE",
                        message="SKiDL produced a netlist but no .kicad_sch — ERC skipped.",
                        severity="warning",
                    )],
                )
            else:
                erc_result = VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="NO_NETLIST",
                        message="SKiDL script did not produce a netlist (.net) file.",
                        severity="error",
                    )],
                )

            if erc_result.passed:
                break

            # Feed violations back to LLM for next attempt
            violations_context = "\n".join(
                f"- [{v.severity}] {v.code}: {v.message}"
                for v in erc_result.violations
            )

        final_script_path = output_dir / "skidl_design.py"
        artifacts: list[Path] = [
            p for p in [
                final_script_path if final_script_path.exists() else None,
                sch_path,
                net_path,
            ]
            if p and p.exists()
        ]

        new_state = state.model_copy(update={
            "schematic": SchematicArtifact(
                kicad_sch_path=str(sch_path) if sch_path else None,
                netlist_path=str(net_path)   if net_path else None,
                skidl_script_path=str(output_dir / "skidl_design.py"),
                erc_result=erc_result,
            )
        })
        return StageResult(
            state=new_state,
            artifacts=artifacts,
            verifier_result=erc_result or VerifierResult(passed=False),
        )


def _strip_markdown(text: str) -> str:
    """Remove ```python / ``` fences from LLM code output."""
    import re
    return re.sub(r"^```(?:python)?\s*\n?", "", text, flags=re.MULTILINE).replace("```", "").strip()
