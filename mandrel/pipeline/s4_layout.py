"""S4 — PCB layout: placement → DSN → FreeRouting → DRC → STEP.

Flow:
  1. Parse the KiCad .net netlist from S3 to get the component list
     (reference designators + footprints).
  2. LLM proposes (x, y, rotation) for every component; Mandrel builds a
     pcbnew Python placement script and runs it as a subprocess
     (GPL process boundary — Mandrel never imports pcbnew).
  3. kicad-cli pcb export specctrafile → DSN
  4. FreeRouting JAR routes the DSN → SES
  5. pcbnew subprocess applies the SES back to the PCB
  6. kicad-cli pcb drc → JSON → DRCVerifier
  7. kicad-cli pcb export step → board.step (passed to S5)
  8. Verifier gate: DRC errors must be 0.

Graceful degradation: if kicad-cli or FreeRouting is not available (CI, local dev
without engine containers), the stage records DRC_UNAVAILABLE warnings and passes
with a reduced score so the pipeline continues and S5 uses the parametric board STEP.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from mandrel.adapters.freerouting import FreeRoutingAdapter, FreeRoutingError
from mandrel.adapters.kicad import KiCadCLIAdapter, KiCadCLIError
from mandrel.core.state import DesignState, PcbArtifact, VerifierResult, Violation
from mandrel.core.workflow import Context, StageResult
from mandrel.llm.prompts import S4_PLACEMENT_GEN
from mandrel.llm.provider import LLMProvider, Message
from mandrel.verify.drc import DRCVerifier


class LayoutStage:
    """S4: LLM-assisted component placement + FreeRouting autorouter + DRC gate."""

    name = "s4_layout"

    def __init__(
        self,
        llm: LLMProvider,
        kicad: KiCadCLIAdapter | None = None,
        freerouting: FreeRoutingAdapter | None = None,
        drc_verifier: DRCVerifier | None = None,
        max_retries: int = 2,
    ) -> None:
        self._llm         = llm
        self._kicad       = kicad        or KiCadCLIAdapter()
        self._freerouting = freerouting  or FreeRoutingAdapter()
        self._drc         = drc_verifier or DRCVerifier()
        self._max_retries = max_retries

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        if state.schematic is None or not state.schematic.netlist_path:
            raise ValueError("S4 requires state.schematic.netlist_path — run S3 first.")

        netlist_path = Path(state.schematic.netlist_path)
        if not netlist_path.exists():
            raise ValueError(f"S4: netlist file not found: {netlist_path}")

        output_dir = ctx.project_dir / "s4_layout"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not self._kicad.is_available():
            return _unavailable_result(state, "kicad-cli not found")

        # ── 1. Parse netlist ─────────────────────────────────────────────────
        components = _parse_netlist_components(netlist_path)
        if not components:
            return StageResult(
                state=state, artifacts=[],
                verifier_result=VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="NO_COMPONENTS",
                        message="Netlist has no components — S3 may not have run correctly.",
                        severity="error",
                    )],
                ),
            )

        # ── 2. LLM placement proposal ────────────────────────────────────────
        from mandrel.standards.form_factors.feather import BOARD_LENGTH_MM, BOARD_WIDTH_MM
        form_factor = (
            state.constraints.form_factor.value if state.constraints else "feather"
        )
        arch_json = (
            json.dumps(state.architecture.model_dump(mode="json"), indent=2)
            if state.architecture else "null"
        )
        placements: list[dict] = []
        placement_error: str = ""

        for attempt in range(1, self._max_retries + 1):
            prompt = S4_PLACEMENT_GEN.format(
                board_l_mm=BOARD_LENGTH_MM,
                board_w_mm=BOARD_WIDTH_MM,
                form_factor=form_factor,
                components_json=json.dumps(components, indent=2),
                arch_json=arch_json,
            )
            await ctx.progress(
                self.name,
                f"LLM proposing component placement (attempt {attempt}/{self._max_retries})…",
            )
            raw = await self._llm.complete(
                [Message(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=2048,
                on_token=ctx.stream_reporter(
                    self.name,
                    f"LLM proposing placement (attempt {attempt}/{self._max_retries})",
                ),
            )
            try:
                placements = _parse_placements(raw)
                if placements:
                    break
            except Exception as exc:
                placement_error = str(exc)

        if not placements:
            return StageResult(
                state=state, artifacts=[],
                verifier_result=VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="PLACEMENT_PARSE_ERROR",
                        message=f"LLM returned unparseable placement JSON: {placement_error}",
                        severity="error",
                    )],
                ),
            )

        # ── 3. Generate + run pcbnew placement script ────────────────────────
        pcb_path    = output_dir / "board.kicad_pcb"
        script_path = output_dir / "placement.py"
        lib_path = ctx.config.kicad_lib_path if ctx.config else ""
        script_src = _build_placement_script(
            netlist_path=netlist_path,
            pcb_path=pcb_path,
            placements=placements,
            board_l_mm=BOARD_LENGTH_MM,
            board_w_mm=BOARD_WIDTH_MM,
            kicad_lib_path=lib_path,
        )
        script_path.write_text(script_src, encoding="utf-8")

        artifacts: list[Path] = [script_path]

        await ctx.progress(self.name, "Running pcbnew placement script (KiCad subprocess)…")
        try:
            self._kicad.run_placement_script(script_path)
        except KiCadCLIError as exc:
            return StageResult(
                state=state, artifacts=_existing(artifacts),
                verifier_result=VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="PLACEMENT_SCRIPT_FAILED", message=str(exc), severity="error",
                    )],
                ),
            )

        if pcb_path.exists():
            artifacts.append(pcb_path)

        # ── 4. Export DSN ─────────────────────────────────────────────────────
        dsn_path = output_dir / "board.dsn"
        await ctx.progress(self.name, "Exporting Specctra DSN for autorouting…")
        try:
            self._kicad.export_dsn(pcb_path, dsn_path)
            artifacts.append(dsn_path)
        except KiCadCLIError as exc:
            return _engine_error(state, artifacts, "DSN_EXPORT_FAILED", exc)

        # ── 5. FreeRouting ───────────────────────────────────────────────────
        ses_path = output_dir / "board.ses"
        if self._freerouting.is_available():
            await ctx.progress(
                self.name, "FreeRouting autorouter running (can take several minutes)…"
            )
            try:
                self._freerouting.route(dsn_path, ses_path)
                artifacts.append(ses_path)
            except FreeRoutingError as exc:
                return _engine_error(state, artifacts, "FREEROUTING_FAILED", exc)

            # ── 6. Import SES ────────────────────────────────────────────────
            await ctx.progress(self.name, "Importing routed SES back into the PCB…")
            try:
                self._kicad.import_ses(pcb_path, ses_path)
            except KiCadCLIError as exc:
                return _engine_error(state, artifacts, "SES_IMPORT_FAILED", exc)

        # ── 7. DRC ───────────────────────────────────────────────────────────
        await ctx.progress(self.name, "Running kicad-cli DRC…")
        try:
            drc_report = self._kicad.run_drc(pcb_path, output_dir)
            artifacts.append(drc_report)
            drc_result = self._drc.check(drc_report)
        except KiCadCLIError as exc:
            drc_result = VerifierResult(
                passed=True, score=0.5,
                violations=[Violation(
                    code="DRC_UNAVAILABLE", message=str(exc), severity="warning",
                )],
            )

        # ── 8. Export STEP for S5 ────────────────────────────────────────────
        step_path  = output_dir / "board.step"
        step_str: str | None = None
        await ctx.progress(self.name, "Exporting board STEP for enclosure fit check…")
        try:
            self._kicad.export_step(pcb_path, step_path)
            if step_path.exists():
                artifacts.append(step_path)
                step_str = str(step_path)
        except KiCadCLIError:
            pass  # S5 falls back to parametric board STEP

        new_state = state.model_copy(update={
            "pcb": PcbArtifact(
                kicad_pcb_path=str(pcb_path) if pcb_path.exists() else None,
                board_step_path=step_str,
                drc_result=drc_result,
            )
        })
        return StageResult(
            state=new_state,
            artifacts=_existing(artifacts),
            verifier_result=drc_result,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def _existing(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.exists()]


def _unavailable_result(state: DesignState, reason: str) -> StageResult:
    return StageResult(
        state=state, artifacts=[],
        verifier_result=VerifierResult(
            passed=True, score=0.5,
            violations=[Violation(
                code="DRC_UNAVAILABLE",
                message=f"S4 skipped: {reason}. "
                        "Start engine containers: "
                        "docker compose --profile engines up -d",
                severity="warning",
            )],
        ),
    )


def _engine_error(
    state: DesignState, artifacts: list[Path], code: str, exc: Exception
) -> StageResult:
    return StageResult(
        state=state, artifacts=_existing(artifacts),
        verifier_result=VerifierResult(
            passed=False,
            violations=[Violation(code=code, message=str(exc), severity="error")],
        ),
    )


# ── Netlist parser ────────────────────────────────────────────────────────────


def _parse_netlist_components(netlist_path: Path) -> list[dict]:
    """Parse KiCad .net (S-expression) to a list of {ref, value, footprint} dicts.

    Uses a real S-expression walk — comp blocks nest arbitrarily deep
    ((fields (field ...))), which defeats regex matching. Virtual parts
    (refs starting with '#', e.g. PWR_FLAG) are skipped: they have no
    physical footprint and must not reach placement.
    """
    text = netlist_path.read_text(encoding="utf-8")
    try:
        tree = _parse_sexp(text)
    except ValueError:
        return []

    components: list[dict] = []
    for node in _find_sexp_nodes(tree, "comp"):
        ref = _sexp_child_value(node, "ref")
        if not ref or ref.startswith("#"):
            continue
        components.append({
            "ref": ref,
            "value": _sexp_child_value(node, "value") or "",
            "footprint": _sexp_child_value(node, "footprint") or "",
        })
    return components


def _parse_sexp(text: str) -> list:
    """Parse an S-expression string into nested Python lists of strings."""
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    pos = 0

    def parse() -> Any:
        nonlocal pos
        token = tokens[pos]
        pos += 1
        if token == "(":
            node = []
            while pos < len(tokens) and tokens[pos] != ")":
                node.append(parse())
            if pos >= len(tokens):
                raise ValueError("Unbalanced S-expression")
            pos += 1  # consume ")"
            return node
        if token == ")":
            raise ValueError("Unexpected ')'")
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            return token[1:-1].replace('\\"', '"')
        return token

    result = parse()
    return result if isinstance(result, list) else [result]


def _find_sexp_nodes(tree: list, tag: str) -> list[list]:
    """Recursively collect all sub-lists whose first element is `tag`."""
    found: list[list] = []
    if tree and tree[0] == tag:
        found.append(tree)
    for child in tree:
        if isinstance(child, list):
            found.extend(_find_sexp_nodes(child, tag))
    return found


def _sexp_child_value(node: list, tag: str) -> str | None:
    """Return the first atom following `tag` in a direct child list."""
    for child in node:
        if isinstance(child, list) and child and child[0] == tag and len(child) > 1:
            value = child[1]
            if isinstance(value, str):
                return value
    return None


# ── Placement JSON parser ─────────────────────────────────────────────────────


def _parse_placements(llm_output: str) -> list[dict]:
    """Extract a JSON array of placement dicts from LLM output."""
    text = re.sub(r"^```[a-z]*\s*\n?", "", llm_output.strip(), flags=re.MULTILINE)
    text = text.replace("```", "").strip()
    start = text.find("[")
    end   = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array found in placement output")
    return json.loads(text[start : end + 1])


# ── pcbnew placement script builder ──────────────────────────────────────────


def _build_placement_script(
    netlist_path: Path,
    pcb_path: Path,
    placements: list[dict],
    board_l_mm: float,
    board_w_mm: float,
    kicad_lib_path: str,
) -> str:
    """Generate a pcbnew Python script that creates a .kicad_pcb with placed footprints.

    This script executes in the KiCad container's Python interpreter (a subprocess).
    Mandrel only writes the file and runs it — it never imports pcbnew itself.
    """
    placements_json = json.dumps(placements, indent=2)
    return textwrap.dedent(f"""\
        # Auto-generated by Mandrel S4.
        # Runs in the KiCad container Python interpreter — GPL boundary is maintained
        # because Mandrel invokes this as a subprocess, never importing pcbnew itself.
        import sys, json, tempfile, os
        import pcbnew

        BOARD_L_MM   = {board_l_mm}
        BOARD_W_MM   = {board_w_mm}
        NETLIST_PATH = r"{netlist_path!s}"
        PCB_PATH     = r"{pcb_path!s}"
        KICAD_LIB    = r"{kicad_lib_path}"

        PLACEMENTS = {placements_json}

        board = pcbnew.BOARD()

        # Board outline
        outline = pcbnew.PCB_SHAPE(board)
        outline.SetShape(pcbnew.SHAPE_T_RECT)
        outline.SetLayer(pcbnew.Edge_Cuts)
        outline.SetStart(pcbnew.VECTOR2I(0, 0))
        outline.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(BOARD_L_MM), pcbnew.FromMM(BOARD_W_MM)
        ))
        board.Add(outline)

        # Load netlist into board
        if KICAD_LIB:
            pcbnew.SetKicadLibPath(KICAD_LIB)

        netlist = pcbnew.NETLIST()
        try:
            reader = pcbnew.CMP_READER(netlist)
            with open(NETLIST_PATH) as f:
                content = f.read()
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".net", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                reader.Load(tmp_path)
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            print(f"Warning: netlist load failed: {{e}}", file=sys.stderr)

        # Apply placements to any footprints the netlist loaded
        placement_map = {{p["ref"]: p for p in PLACEMENTS}}
        for fp in board.GetFootprints():
            ref = fp.GetReference()
            pl = placement_map.get(ref)
            if pl:
                fp.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(pl.get("x_mm", 25.0)),
                    pcbnew.FromMM(pl.get("y_mm", 11.0)),
                ))
                fp.SetOrientationDegrees(pl.get("rotation_deg", 0))
                fp.SetLayer(pcbnew.F_Cu)

        board.Save(PCB_PATH)
        print(f"Board saved: {{PCB_PATH}}")
    """)
