"""S2 — Architecture: ProductSpec → block diagram + human checkpoint.

Flow:
  1. LLM proposes a block-level architecture (MCU, peripherals, power topology)
     as a JSON object aligned with the Architecture schema.
  2. ArchitectureVerifier checks structural integrity (no dangling connections,
     no duplicate block IDs, MCU present).
  3. Human checkpoint fires so the engineer can confirm the architecture before
     S3 commits to generating a full schematic.

The architecture is intentionally high-level — part numbers are proposed but not
yet verified against distributor stock (that happens in S6).
"""

from __future__ import annotations

import json
import re

from mandrel.core.state import (
    Architecture,
    Block,
    Connection,
    DesignState,
    VerifierResult,
    Violation,
)
from mandrel.core.workflow import Context, StageResult
from mandrel.llm.prompts import S2_ARCH_GEN
from mandrel.llm.provider import LLMProvider, Message
from mandrel.verify.architecture import ArchitectureVerifier


class ArchitectureStage:
    """S2: propose and validate a block-level architecture from the ProductSpec."""

    name = "s2_architecture"

    def __init__(
        self,
        llm: LLMProvider,
        verifier: ArchitectureVerifier | None = None,
        max_retries: int = 2,
    ) -> None:
        self._llm      = llm
        self._verifier = verifier or ArchitectureVerifier()
        self._max_retries = max_retries

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        if state.spec is None:
            raise ValueError("S2 requires state.spec — run S1 first.")

        output_dir = ctx.project_dir / "s2_architecture"
        output_dir.mkdir(parents=True, exist_ok=True)

        spec_json     = json.dumps(state.spec.model_dump(mode="json"), indent=2)
        form_factor   = state.constraints.form_factor.value if state.constraints else "custom"
        violations_ctx = ""
        arch: Architecture | None = None
        result: VerifierResult | None = None

        for attempt in range(1, self._max_retries + 1):
            prompt = S2_ARCH_GEN.format(
                spec_json=spec_json,
                form_factor=form_factor,
            )
            if violations_ctx:
                prompt += f"\n\nPREVIOUS STRUCTURAL VIOLATIONS (fix these):\n{violations_ctx}"

            response = await self._llm.complete(
                [Message(role="user", content=prompt)],
                temperature=0.2,
            )

            try:
                arch = _parse_architecture(response)
            except ValueError as exc:
                if attempt == self._max_retries:
                    return StageResult(
                        state=state,
                        artifacts=[],
                        verifier_result=VerifierResult(
                            passed=False,
                            violations=[Violation(
                                code="ARCH_PARSE_ERROR",
                                message=str(exc),
                                severity="error",
                            )],
                        ),
                    )
                violations_ctx = f"JSON parse error: {exc}"
                continue

            result = self._verifier.check(arch)
            if result.passed:
                break

            violations_ctx = "\n".join(
                f"- [{v.severity}] {v.code}: {v.message}"
                for v in result.violations
            )

        if arch is None or result is None:
            return StageResult(
                state=state,
                artifacts=[],
                verifier_result=VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="ARCH_GEN_FAILED",
                        message="Architecture generation failed after all retries.",
                        severity="error",
                    )],
                ),
            )

        # Persist the architecture JSON for human review
        arch_path = output_dir / "architecture.json"
        arch_path.write_text(
            json.dumps(arch.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        new_state = state.model_copy(update={"architecture": arch})
        return StageResult(
            state=new_state,
            artifacts=[arch_path],
            verifier_result=result,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_architecture(llm_output: str) -> Architecture:
    """Extract and parse the Architecture JSON from the LLM response."""
    data = _extract_json(llm_output)

    blocks = [
        Block(
            id=b["id"],
            label=b["label"],
            proposed_mpn=b.get("proposed_mpn"),
            kicad_lib=b.get("kicad_lib"),
        )
        for b in data.get("blocks", [])
    ]

    connections = [
        Connection(
            from_block=c["from_block"],
            to_block=c["to_block"],
            signal=c["signal"],
        )
        for c in data.get("connections", [])
    ]

    return Architecture(blocks=blocks, connections=connections)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object from the LLM response (handles markdown fences)."""
    clean = re.sub(r"```(?:json)?\s*", "", text).strip().strip("`").strip()
    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in LLM response:\n{text[:500]}")
    try:
        return json.loads(clean[start:end])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}\n{clean[start:end][:500]}") from exc
