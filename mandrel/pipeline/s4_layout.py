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
from mandrel.standards.form_factors import feather_template
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
        max_layout_attempts: int = 3,
    ) -> None:
        self._llm         = llm
        self._kicad       = kicad        or KiCadCLIAdapter()
        self._freerouting = freerouting  or FreeRoutingAdapter()
        self._drc         = drc_verifier or DRCVerifier()
        self._max_retries = max_retries            # JSON-parse retries per proposal
        self._max_layout_attempts = max_layout_attempts  # full place→route→DRC cycles

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

        # ── 2. Prepare placement context ─────────────────────────────────────
        from mandrel.standards.form_factors.feather import BOARD_LENGTH_MM, BOARD_WIDTH_MM
        form_factor = (
            state.constraints.form_factor.value if state.constraints else "feather"
        )
        arch_json = (
            json.dumps(state.architecture.model_dump(mode="json"), indent=2)
            if state.architecture else "null"
        )
        fp_lib_path = (
            ctx.config.kicad_footprint_path
            if ctx.config and getattr(ctx.config, "kicad_footprint_path", None)
            else "/usr/share/kicad/footprints"
        )
        # Real courtyard dimensions from the .kicad_mod files — the LLM places
        # blind without them, which is the main source of overlap violations.
        _attach_courtyard_sizes(components, fp_lib_path)
        nets = _parse_netlist_nets(netlist_path)

        # Deterministic Feather template: the LLM only places free interior
        # parts into the keep-in rectangle; USB-C is locked to the short edge
        # at the correct rotation (overrides whatever the LLM proposes).
        keep_in = feather_template.keep_in_rect(BOARD_LENGTH_MM, BOARD_WIDTH_MM)
        usb_fixed = feather_template.usb_c_fixed_placements(components, BOARD_WIDTH_MM)
        free_components = [c for c in components if c["ref"] not in usb_fixed]

        # Design-knowledge: pull placement best-practices relevant to the parts
        # on this board. The rules drive both the LLM prompt and the explainable
        # post-placement evaluation (paid KB; empty for the OSS core).
        knowledge_rules = _placement_rules(components, form_factor)
        knowledge_text = _format_rules(knowledge_rules)

        pcb_path    = output_dir / "board.kicad_pcb"
        script_path = output_dir / "placement.py"
        dsn_path    = output_dir / "board.dsn"
        ses_path    = output_dir / "board.ses"
        artifacts: list[Path] = []
        drc_result: VerifierResult | None = None
        drc_feedback = ""

        # ── 3. Layout repair loop: place → route → DRC → feed errors back ────
        for layout_attempt in range(1, self._max_layout_attempts + 1):
            placements = await self._propose_placements(
                ctx, free_components, arch_json, form_factor,
                BOARD_LENGTH_MM, BOARD_WIDTH_MM, drc_feedback, keep_in,
                knowledge_text,
            )
            if not placements:
                return StageResult(
                    state=state, artifacts=_existing(artifacts),
                    verifier_result=VerifierResult(
                        passed=False,
                        violations=[Violation(
                            code="PLACEMENT_PARSE_ERROR",
                            message="LLM returned unparseable placement JSON.",
                            severity="error",
                        )],
                    ),
                )
            # Locked template parts (USB-C) override the LLM proposal.
            placements = [p for p in placements if p.get("ref") not in usb_fixed]
            placements.extend(usb_fixed.values())

            # Deterministic overlap resolution: the LLM gives a rough, sensible
            # arrangement; this guarantees no courtyard overlaps (the dominant
            # DRC failure) by spreading parts apart using real courtyard sizes,
            # keeping fixed parts put and staying inside the keep-in rectangle.
            _resolve_overlaps(placements, components, keep_in, set(usb_fixed))

            script_src = _build_placement_script(
                pcb_path=pcb_path,
                components=components,
                nets=nets,
                placements=placements,
                board_l_mm=BOARD_LENGTH_MM,
                board_w_mm=BOARD_WIDTH_MM,
                footprint_lib_path=fp_lib_path,
                dsn_path=dsn_path,
            )
            script_path.write_text(script_src, encoding="utf-8")
            if script_path not in artifacts:
                artifacts.append(script_path)

            await ctx.progress(
                self.name, "Running pcbnew placement script (KiCad subprocess)…"
            )
            try:
                self._kicad.run_placement_script(script_path)
            except KiCadCLIError as exc:
                return StageResult(
                    state=state, artifacts=_existing(artifacts),
                    verifier_result=VerifierResult(
                        passed=False,
                        violations=[Violation(
                            code="PLACEMENT_SCRIPT_FAILED",
                            message=str(exc),
                            severity="error",
                        )],
                    ),
                )
            if pcb_path.exists() and pcb_path not in artifacts:
                artifacts.append(pcb_path)

            # The placement script exports the DSN itself (the netclass rules
            # only exist on its in-memory board object).
            if not dsn_path.exists():
                return _engine_error(
                    state, artifacts, "DSN_EXPORT_FAILED",
                    RuntimeError("placement script did not produce a DSN file"),
                )
            if dsn_path not in artifacts:
                artifacts.append(dsn_path)

            if self._freerouting.is_available():
                await ctx.progress(
                    self.name,
                    f"FreeRouting autorouter running (layout attempt "
                    f"{layout_attempt}/{self._max_layout_attempts}; can take minutes)…",
                )
                try:
                    self._freerouting.route(dsn_path, ses_path)
                    if ses_path not in artifacts:
                        artifacts.append(ses_path)
                except FreeRoutingError as exc:
                    return _engine_error(state, artifacts, "FREEROUTING_FAILED", exc)

                await ctx.progress(self.name, "Importing routed SES back into the PCB…")
                try:
                    self._kicad.import_ses(pcb_path, ses_path)
                except KiCadCLIError as exc:
                    return _engine_error(state, artifacts, "SES_IMPORT_FAILED", exc)

            await ctx.progress(self.name, "Running kicad-cli DRC…")
            try:
                drc_report = self._kicad.run_drc(pcb_path, output_dir)
                if drc_report not in artifacts:
                    artifacts.append(drc_report)
                drc_result = self._drc.check(drc_report)
            except KiCadCLIError as exc:
                drc_result = VerifierResult(
                    passed=True, score=0.5,
                    violations=[Violation(
                        code="DRC_UNAVAILABLE", message=str(exc), severity="warning",
                    )],
                )
                break

            if drc_result.passed:
                break

            errors = [v for v in drc_result.violations if v.severity == "error"]
            drc_feedback = "\n".join(f"- {v.code}: {v.message}" for v in errors[:30])
            if layout_attempt < self._max_layout_attempts:
                await ctx.progress(
                    self.name,
                    f"DRC found {len(errors)} errors — revising placement "
                    f"(attempt {layout_attempt + 1}/{self._max_layout_attempts})…",
                )

        # ── 4. Export STEP for S5 ────────────────────────────────────────────
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

        if drc_result is None:  # defensive: loop always sets it
            drc_result = VerifierResult(passed=False, score=0.0)

        # Explainable KB evaluation of the final placement — the "why" the UI
        # shows (which best-practices applied, what was measured, pass/fail).
        rationale = _evaluate_placement_rules(components, placements, knowledge_rules)
        if rationale:
            n_fail = sum(1 for r in rationale if r.get("status") == "fail")
            await ctx.progress(
                self.name,
                f"Evaluated layout against {len(rationale)} design rules "
                f"({n_fail} not yet met).",
            )

        new_state = state.model_copy(update={
            "pcb": PcbArtifact(
                kicad_pcb_path=str(pcb_path) if pcb_path.exists() else None,
                board_step_path=step_str,
                drc_result=drc_result,
                placement_rationale=rationale,
            )
        })
        return StageResult(
            state=new_state,
            artifacts=_existing(artifacts),
            verifier_result=drc_result,
        )

    async def _propose_placements(
        self,
        ctx: Context,
        components: list[dict],
        arch_json: str,
        form_factor: str,
        board_l_mm: float,
        board_w_mm: float,
        drc_feedback: str,
        keep_in: tuple[float, float, float, float],
        knowledge_text: str = "",
    ) -> list[dict]:
        """LLM placement proposal with JSON-parse retries.

        On repair iterations, drc_feedback carries the previous layout's DRC
        errors so the model can move the offending parts.
        """
        kx0, ky0, kx1, ky1 = keep_in
        knowledge_block = (
            f"\n\nDESIGN BEST-PRACTICES (apply these — they are domain rules, not "
            f"suggestions):\n{knowledge_text}\n" if knowledge_text else ""
        )
        for attempt in range(1, self._max_retries + 1):
            prompt = S4_PLACEMENT_GEN.format(
                board_l_mm=board_l_mm,
                board_w_mm=board_w_mm,
                form_factor=form_factor,
                components_json=json.dumps(components, indent=2),
                arch_json=arch_json,
                keep_in_x0=kx0, keep_in_y0=ky0, keep_in_x1=kx1, keep_in_y1=ky1,
            ) + knowledge_block
            if drc_feedback:
                prompt += (
                    "\n\nYOUR PREVIOUS LAYOUT FAILED DRC. Revise the positions to "
                    "fix these violations (coordinates are mm from board origin; "
                    "move the parts involved apart):\n" + drc_feedback
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
                    return placements
            except Exception:
                continue
        return []


# ── Module-level helpers ──────────────────────────────────────────────────────


def _existing(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.exists()]


def _resolve_overlaps(
    placements: list[dict],
    components: list[dict],
    keep_in: tuple[float, float, float, float],
    fixed_refs: set[str],
    min_gap_mm: float = 0.5,
    iterations: int = 300,
) -> None:
    """Spread overlapping components apart in place (relaxation).

    Uses each part's real courtyard size; pushes overlapping pairs along the
    axis of least penetration, never moves fixed parts (USB-C), and clamps
    everything to the keep-in rectangle. Mutates the placement dicts. This
    deterministically eliminates COURTYARDS_OVERLAP — the dominant S4 failure —
    and, by clearing the parts apart, unblocks routing.
    """
    size = {c["ref"]: (c.get("size_mm") or [1.0, 1.0]) for c in components if "ref" in c}
    pos = {p["ref"]: [float(p.get("x_mm", 0.0)), float(p.get("y_mm", 0.0))]
           for p in placements if "ref" in p}
    refs = list(pos)
    x0, y0, x1, y1 = keep_in

    def clamp(ref: str) -> None:
        if ref in fixed_refs:
            return
        w, h = size.get(ref, [1.0, 1.0])
        pos[ref][0] = min(max(pos[ref][0], x0 + w / 2), x1 - w / 2)
        pos[ref][1] = min(max(pos[ref][1], y0 + h / 2), y1 - h / 2)

    for _ in range(iterations):
        moved = False
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a, b = refs[i], refs[j]
                wa, ha = size.get(a, [1.0, 1.0])
                wb, hb = size.get(b, [1.0, 1.0])
                reqx = (wa + wb) / 2 + min_gap_mm
                reqy = (ha + hb) / 2 + min_gap_mm
                dx = pos[b][0] - pos[a][0]
                dy = pos[b][1] - pos[a][1]
                ox = reqx - abs(dx)
                oy = reqy - abs(dy)
                if ox <= 0 or oy <= 0:
                    continue  # no overlap on at least one axis
                # push along the axis of least penetration
                a_fixed = a in fixed_refs
                b_fixed = b in fixed_refs
                share_a = 0.0 if a_fixed else (1.0 if b_fixed else 0.5)
                share_b = 0.0 if b_fixed else (1.0 if a_fixed else 0.5)
                if ox < oy:
                    s = 1.0 if dx >= 0 else -1.0
                    pos[a][0] -= s * ox * share_a
                    pos[b][0] += s * ox * share_b
                else:
                    s = 1.0 if dy >= 0 else -1.0
                    pos[a][1] -= s * oy * share_a
                    pos[b][1] += s * oy * share_b
                clamp(a)
                clamp(b)
                moved = True
        if not moved:
            break

    for p in placements:
        r = p.get("ref")
        if r in pos:
            p["x_mm"] = round(pos[r][0], 3)
            p["y_mm"] = round(pos[r][1], 3)


def _placement_rules(components: list[dict], form_factor: str) -> list:
    """Retrieve placement-relevant design rules for the parts on this board.

    Returns DesignRule objects (empty when no KB is active — OSS core uses the
    NullKnowledgeProvider). Never raises into the pipeline.
    """
    try:
        from mandrel.knowledge import RuleQuery, get_provider
        from mandrel.knowledge.classify import classify_all

        provider = get_provider()
        if provider.is_empty():
            return []
        return provider.query(RuleQuery(
            stage="s4_layout",
            categories=["spacing", "orientation", "connector", "placement",
                        "decoupling", "oscillator", "rf", "ground_plane"],
            part_classes=classify_all(components),
            form_factor=form_factor,
        ))
    except Exception:
        return []


def _format_rules(rules: list) -> str:
    try:
        from mandrel.knowledge.provider import format_rules_for_prompt
        return format_rules_for_prompt(rules)
    except Exception:
        return ""


def _evaluate_placement_rules(components, placements, rules) -> list[dict]:
    """Explainable evaluation of the final placement against the KB rules."""
    if not rules:
        return []
    try:
        from mandrel.knowledge.evaluate import evaluate_placement
        return [e.model_dump() for e in evaluate_placement(components, placements, rules)]
    except Exception:
        return []


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


def _attach_courtyard_sizes(components: list[dict], fp_lib_dir: str) -> None:
    """Add "size_mm": [w, h] (courtyard bbox) to each component in place."""
    cache: dict[str, list[float] | None] = {}
    for comp in components:
        fp = comp.get("footprint") or ""
        if fp not in cache:
            cache[fp] = _footprint_size_mm(fp, fp_lib_dir)
        if cache[fp]:
            comp["size_mm"] = cache[fp]


def _footprint_size_mm(fp_field: str, fp_lib_dir: str) -> list[float] | None:
    """Courtyard bounding box [w, h] of a footprint, parsed from its .kicad_mod.

    Falls back to the pad extents when no courtyard is drawn. Returns None when
    the footprint file can't be found or parsed.
    """
    if ":" not in fp_field:
        return None
    lib, name = fp_field.split(":", 1)
    path = Path(fp_lib_dir) / f"{lib}.pretty" / f"{name}.kicad_mod"
    if not path.exists():
        return None
    try:
        tree = _parse_sexp(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    xs: list[float] = []
    ys: list[float] = []

    def on_courtyard(node: list) -> bool:
        for ch in node:
            if isinstance(ch, list) and ch and ch[0] == "layer" and len(ch) > 1:
                return "CrtYd" in str(ch[1])
        return False

    def collect_points(node: list) -> None:
        for ch in node:
            if not isinstance(ch, list) or not ch:
                continue
            if ch[0] in ("start", "end", "center") and len(ch) > 2:
                try:
                    xs.append(float(ch[1]))
                    ys.append(float(ch[2]))
                except ValueError:
                    pass
            elif ch[0] == "pts":
                for xy in ch[1:]:
                    if isinstance(xy, list) and xy and xy[0] == "xy" and len(xy) > 2:
                        try:
                            xs.append(float(xy[1]))
                            ys.append(float(xy[2]))
                        except ValueError:
                            pass

    for tag in ("fp_line", "fp_rect", "fp_poly", "fp_circle"):
        for node in _find_sexp_nodes(tree, tag):
            if on_courtyard(node):
                collect_points(node)

    if not xs:  # no courtyard drawn — use pad extents
        for node in _find_sexp_nodes(tree, "pad"):
            at = next((c for c in node if isinstance(c, list) and c and c[0] == "at"), None)
            size = next((c for c in node if isinstance(c, list) and c and c[0] == "size"), None)
            if at is None or size is None or len(at) < 3 or len(size) < 3:
                continue
            try:
                x, y = float(at[1]), float(at[2])
                w, h = float(size[1]), float(size[2])
            except ValueError:
                continue
            xs.extend([x - w / 2, x + w / 2])
            ys.extend([y - h / 2, y + h / 2])

    if not xs:
        return None
    return [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)]


def _parse_netlist_nets(netlist_path: Path) -> list[dict]:
    """Parse the nets section: [{name, nodes: [[ref, pin], ...]}, ...]."""
    text = netlist_path.read_text(encoding="utf-8")
    try:
        tree = _parse_sexp(text)
    except ValueError:
        return []

    nets: list[dict] = []
    for net_node in _find_sexp_nodes(tree, "net"):
        name = _sexp_child_value(net_node, "name")
        if not name:
            continue
        nodes = []
        for child in net_node:
            if isinstance(child, list) and child and child[0] == "node":
                ref = _sexp_child_value(child, "ref")
                pin = _sexp_child_value(child, "pin")
                if ref and pin and not ref.startswith("#"):
                    nodes.append([ref, pin])
        if nodes:
            nets.append({"name": name, "nodes": nodes})
    return nets


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


_PLACEMENT_SCRIPT_TEMPLATE = textwrap.dedent("""\
    # Auto-generated by Mandrel S4.
    # Runs in the KiCad Python interpreter — GPL boundary is maintained because
    # Mandrel invokes this as a subprocess, never importing pcbnew itself.
    # Uses only APIs verified against KiCad 9: FootprintLoad, NETINFO_ITEM,
    # SetOrientationDegrees, pad.SetNet.
    import sys
    import pcbnew

    BOARD_L_MM = {board_l_mm}
    BOARD_W_MM = {board_w_mm}
    PCB_PATH   = r"{pcb_path}"
    DSN_PATH   = r"{dsn_path}"
    FP_LIB_DIR = r"{footprint_lib_path}"

    COMPONENTS = {components_json}
    PLACEMENTS = {placements_json}
    NETS       = {nets_json}

    board = pcbnew.BOARD()

    # __MANDREL_TEMPLATE_OUTLINE__

    # Nets
    net_map = {{}}
    for n in NETS:
        ni = pcbnew.NETINFO_ITEM(board, n["name"])
        board.Add(ni)
        net_map[n["name"]] = ni

    # (ref, pad-number) -> net name
    pad_net = {{}}
    for n in NETS:
        for ref, pin in n["nodes"]:
            pad_net[(ref, str(pin))] = n["name"]

    placement_map = {{p["ref"]: p for p in PLACEMENTS}}
    missing = []

    for comp in COMPONENTS:
        fp_field = comp.get("footprint") or ""
        if ":" not in fp_field:
            missing.append((comp["ref"], fp_field or "<no footprint>"))
            continue
        lib, fp_name = fp_field.split(":", 1)
        try:
            fp = pcbnew.FootprintLoad(FP_LIB_DIR + "/" + lib + ".pretty", fp_name)
        except Exception:
            fp = None
        if fp is None:
            missing.append((comp["ref"], fp_field))
            continue

        fp.SetReference(comp["ref"])
        fp.SetValue(comp.get("value", ""))
        board.Add(fp)

        pl = placement_map.get(comp["ref"])
        if pl:
            fp.SetPosition(pcbnew.VECTOR2I(
                pcbnew.FromMM(float(pl.get("x_mm", 25.0))),
                pcbnew.FromMM(float(pl.get("y_mm", 11.0))),
            ))
            fp.SetOrientationDegrees(float(pl.get("rotation_deg", 0)))

        for pad in fp.Pads():
            net_name = pad_net.get((comp["ref"], pad.GetNumber()))
            if net_name and net_name in net_map:
                pad.SetNet(net_map[net_name])

    for ref, fp_field in missing:
        print(f"WARN: no footprint for {{ref}} ({{fp_field}})", file=sys.stderr)

    if not board.GetFootprints():
        print("ERROR: no footprints could be loaded", file=sys.stderr)
        raise SystemExit(1)

    # 5-mil rules (0.15 mm track / 0.127 mm clearance): required for escape
    # routing on 0.4 mm-pitch QFN packages, within standard fab capability.
    # Must be set BEFORE Save so the .kicad_pro serializes them — netclasses
    # live in the project file and kicad-cli DRC reads them from there.
    nc = board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(pcbnew.FromMM(0.15))
    nc.SetClearance(pcbnew.FromMM(0.127))
    nc.SetViaDiameter(pcbnew.FromMM(0.6))
    nc.SetViaDrill(pcbnew.FromMM(0.3))

    board.Save(PCB_PATH)

    # Export the Specctra DSN here, while the netclass is set on the live
    # board object — a fresh LoadBoard in another process would reset the
    # rules to defaults and FreeRouting could not escape the QFN.
    if DSN_PATH:
        if not pcbnew.ExportSpecctraDSN(board, DSN_PATH):
            print("ERROR: DSN export failed", file=sys.stderr)
            raise SystemExit(1)

    # Fine-pitch QFN packages (e.g. RP2040, 0.4 mm pitch) inevitably trigger
    # solder_mask_bridge with the default mask expansion; fabs resolve these
    # in CAM. Downgrade that one rule to warning at the project level so DRC
    # gates on real electrical/mechanical errors.
    import json as _json
    import os as _os
    _pro_path = PCB_PATH[: -len(".kicad_pcb")] + ".kicad_pro"
    if _os.path.exists(_pro_path):
        with open(_pro_path) as _f:
            _pro = _json.load(_f)
        _sev = (
            _pro.setdefault("board", {{}})
                .setdefault("design_settings", {{}})
                .setdefault("rule_severities", {{}})
        )
        _sev["solder_mask_bridge"] = "warning"
        with open(_pro_path, "w") as _f:
            _json.dump(_pro, _f, indent=2)

    print(f"Board saved: {{PCB_PATH}} with {{len(board.GetFootprints())}} footprints")
""")


def _build_placement_script(
    pcb_path: Path,
    components: list[dict],
    nets: list[dict],
    placements: list[dict],
    board_l_mm: float,
    board_w_mm: float,
    footprint_lib_path: str,
    dsn_path: Path | None = None,
) -> str:
    """Generate a pcbnew Python script that builds a .kicad_pcb from the parsed
    netlist (components + nets) and the LLM's placement proposal.

    The template is dedented BEFORE substitution: interpolated JSON is
    multi-line and would otherwise destroy the common indent. The deterministic
    Feather outline + mounting holes are spliced in via a marker replace (after
    format) so the emitted pcbnew source never passes through str.format.
    """
    script = _PLACEMENT_SCRIPT_TEMPLATE.format(
        board_l_mm=board_l_mm,
        board_w_mm=board_w_mm,
        pcb_path=str(pcb_path),
        dsn_path=str(dsn_path) if dsn_path else "",
        footprint_lib_path=footprint_lib_path,
        components_json=json.dumps(components, indent=2),
        placements_json=json.dumps(placements, indent=2),
        nets_json=json.dumps(nets, indent=2),
    )
    outline_src = feather_template.outline_and_holes_src(board_l_mm, board_w_mm)
    return script.replace("# __MANDREL_TEMPLATE_OUTLINE__", outline_src)
