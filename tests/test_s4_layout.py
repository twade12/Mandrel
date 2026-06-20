"""Tests for S4 PCB layout stage and supporting components."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mandrel.adapters.freerouting import FreeRoutingAdapter, FreeRoutingError
from mandrel.core.state import (
    Architecture,
    Block,
    Connection,
    DesignState,
    ProductSpec,
    SchematicArtifact,
)
from mandrel.core.workflow import Context
from mandrel.pipeline.s4_layout import (
    LayoutStage,
    _build_placement_script,
    _parse_netlist_components,
    _parse_placements,
)
from mandrel.verify.drc import DRCVerifier

# ── Fixtures ──────────────────────────────────────────────────────────────────


SAMPLE_NETLIST = """\
(net_list
 (components
  (comp (ref U1) (value RP2040) (footprint Package_DFN_QFN:QFN-56))
  (comp (ref U2) (value MIC5219) (footprint Package_TO_SOT_SMD:SOT-23-5))
  (comp (ref C1) (value 100nF) (footprint Capacitor_SMD:C_0402))
 )
 (nets
  (net (num 1) (name "+3V3") (node (ref U1) (pin 1)) (node (ref U2) (pin 3)))
  (net (num 2) (name "GND")  (node (ref U1) (pin 2)))
 )
)
"""

SAMPLE_DRC_CLEAN = json.dumps({
    "errors": 0,
    "warnings": 1,
    "violations": [
        {
            "type": "courtyard_overlap",
            "description": "Courtyard overlap between C1 and U1",
            "severity": "warning",
            "items": [{"description": "C1", "pos": {"x": 10.0, "y": 5.0}}],
        }
    ],
})

SAMPLE_DRC_ERRORS = json.dumps({
    "errors": 2,
    "warnings": 0,
    "violations": [
        {
            "type": "clearance",
            "description": "Copper clearance violation between U1/pad1 and C1/pad1",
            "severity": "error",
            "items": [],
        },
        {
            "type": "hole_clearance",
            "description": "Hole clearance violation",
            "severity": "error",
            "items": [],
        },
    ],
})

SAMPLE_PLACEMENTS = [
    {"ref": "U1", "x_mm": 25.0, "y_mm": 11.0, "rotation_deg": 0, "side": "front"},
    {"ref": "U2", "x_mm": 42.0, "y_mm": 5.0,  "rotation_deg": 0, "side": "front"},
    {"ref": "C1", "x_mm": 22.0, "y_mm": 8.0,  "rotation_deg": 0, "side": "front"},
]


def _write_netlist(path: Path, content: str = SAMPLE_NETLIST) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _state_with_netlist(tmp_path: Path) -> tuple[DesignState, Path]:
    netlist = _write_netlist(tmp_path / "netlist.net")
    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=Architecture(
            blocks=[
                Block(id="mcu",  label="RP2040",   proposed_mpn="SC0914(7)"),
                Block(id="ldo",  label="MIC5219",  proposed_mpn="MIC5219-3.3YM5"),
                Block(id="cap1", label="100nF cap", proposed_mpn=None),
            ],
            connections=[Connection(from_block="mcu", to_block="ldo", signal="+3V3")],
        ),
        schematic=SchematicArtifact(
            netlist_path=str(netlist),
            kicad_sch_path=str(tmp_path / "schematic.kicad_sch"),
        ),
    )
    return state, netlist


# ── _parse_netlist_components ─────────────────────────────────────────────────


def test_parse_netlist_finds_all_refs():
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False) as f:
        f.write(SAMPLE_NETLIST)
        tmp = Path(f.name)
    try:
        comps = _parse_netlist_components(tmp)
    finally:
        tmp.unlink()
    refs = [c["ref"] for c in comps]
    assert "U1" in refs
    assert "U2" in refs
    assert "C1" in refs
    assert len(comps) == 3


def test_parse_netlist_captures_footprint():
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False) as f:
        f.write(SAMPLE_NETLIST)
        tmp = Path(f.name)
    try:
        comps = _parse_netlist_components(tmp)
    finally:
        tmp.unlink()
    u1 = next(c for c in comps if c["ref"] == "U1")
    assert "QFN" in u1["footprint"]


def test_parse_netlist_empty_returns_empty(tmp_path: Path):
    nl = tmp_path / "empty.net"
    nl.write_text("(net_list)", encoding="utf-8")
    assert _parse_netlist_components(nl) == []


# ── _parse_placements ─────────────────────────────────────────────────────────


def test_parse_placements_bare_array():
    raw = json.dumps(SAMPLE_PLACEMENTS)
    result = _parse_placements(raw)
    assert len(result) == 3
    assert result[0]["ref"] == "U1"


def test_parse_placements_strips_markdown():
    raw = "```json\n" + json.dumps(SAMPLE_PLACEMENTS) + "\n```"
    result = _parse_placements(raw)
    assert len(result) == 3


def test_parse_placements_raises_on_garbage():
    with pytest.raises(Exception):
        _parse_placements("Here are the placements: no JSON here, sorry")


# ── DRCVerifier ───────────────────────────────────────────────────────────────


def test_drc_verifier_passes_zero_errors(tmp_path: Path):
    report = tmp_path / "drc.json"
    report.write_text(SAMPLE_DRC_CLEAN, encoding="utf-8")
    result = DRCVerifier().check(report)
    assert result.passed is True
    assert any(v.severity == "warning" for v in result.violations)


def test_drc_verifier_fails_with_errors(tmp_path: Path):
    report = tmp_path / "drc.json"
    report.write_text(SAMPLE_DRC_ERRORS, encoding="utf-8")
    result = DRCVerifier().check(report)
    assert result.passed is False
    assert result.score < 1.0
    assert len([v for v in result.violations if v.severity == "error"]) == 2


def test_drc_verifier_handles_missing_file(tmp_path: Path):
    result = DRCVerifier().check(tmp_path / "nonexistent.json")
    assert result.passed is False
    assert result.violations[0].code == "DRC_PARSE_ERROR"


def test_drc_verifier_handles_invalid_json(tmp_path: Path):
    report = tmp_path / "drc.json"
    report.write_text("not json {{{", encoding="utf-8")
    result = DRCVerifier().check(report)
    assert result.passed is False


# ── FreeRoutingAdapter ────────────────────────────────────────────────────────


def test_freerouting_unavailable_when_no_jar(tmp_path: Path):
    adapter = FreeRoutingAdapter(jar_path=str(tmp_path / "nonexistent.jar"))
    assert adapter.is_available() is False


def test_freerouting_raises_when_unavailable(tmp_path: Path):
    adapter = FreeRoutingAdapter(jar_path=str(tmp_path / "missing.jar"))
    with pytest.raises(FreeRoutingError, match="not found"):
        adapter.route(tmp_path / "in.dsn", tmp_path / "out.ses")


# ── _build_placement_script ───────────────────────────────────────────────────


SAMPLE_COMPONENTS = [
    {"ref": "U1", "value": "RP2040", "footprint": "Package_DFN_QFN:QFN-56"},
    {"ref": "U2", "value": "MIC5219", "footprint": "Package_TO_SOT_SMD:SOT-23-5"},
    {"ref": "C1", "value": "100nF", "footprint": "Capacitor_SMD:C_0402"},
]

SAMPLE_NETS = [
    {"name": "+3V3", "nodes": [["U1", "1"], ["U2", "3"]]},
    {"name": "GND", "nodes": [["U1", "2"]]},
]


def test_build_placement_script_contains_board_dims(tmp_path: Path):
    script = _build_placement_script(
        pcb_path=tmp_path / "board.kicad_pcb",
        components=SAMPLE_COMPONENTS,
        nets=SAMPLE_NETS,
        placements=SAMPLE_PLACEMENTS,
        board_l_mm=50.8,
        board_w_mm=22.86,
        footprint_lib_path="/usr/share/kicad/footprints",
    )
    assert "50.8" in script
    assert "22.86" in script
    assert "pcbnew" in script


def test_build_placement_script_embeds_placements(tmp_path: Path):
    script = _build_placement_script(
        pcb_path=tmp_path / "board.kicad_pcb",
        components=SAMPLE_COMPONENTS,
        nets=SAMPLE_NETS,
        placements=SAMPLE_PLACEMENTS,
        board_l_mm=50.8,
        board_w_mm=22.86,
        footprint_lib_path="",
    )
    assert '"U1"' in script
    assert "25.0" in script


def test_build_placement_script_is_valid_python(tmp_path: Path):
    """Dedent-then-format must yield syntactically valid code even with
    multi-line interpolated JSON (regression: IndentationError at runtime)."""
    import ast
    script = _build_placement_script(
        pcb_path=tmp_path / "board.kicad_pcb",
        components=SAMPLE_COMPONENTS,
        nets=SAMPLE_NETS,
        placements=SAMPLE_PLACEMENTS,
        board_l_mm=50.8,
        board_w_mm=22.86,
        footprint_lib_path="/usr/share/kicad/footprints",
    )
    ast.parse(script)


def test_parse_netlist_nets():
    import tempfile

    from mandrel.pipeline.s4_layout import _parse_netlist_nets
    with tempfile.NamedTemporaryFile(mode="w", suffix=".net", delete=False) as f:
        f.write(SAMPLE_NETLIST)
        tmp = Path(f.name)
    try:
        nets = _parse_netlist_nets(tmp)
    finally:
        tmp.unlink()
    names = [n["name"] for n in nets]
    assert "+3V3" in names
    v33 = next(n for n in nets if n["name"] == "+3V3")
    assert ["U1", "1"] in v33["nodes"]


# ── LayoutStage integration (mocked adapters) ─────────────────────────────────


def _mock_llm(placements: list[dict]) -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=json.dumps(placements))
    return llm


@pytest.mark.asyncio
async def test_s4_skips_gracefully_when_kicad_unavailable(tmp_path: Path) -> None:
    """When kicad-cli is not available, S4 returns a passing warning result."""
    state, _ = _state_with_netlist(tmp_path)
    llm = _mock_llm(SAMPLE_PLACEMENTS)

    kicad = MagicMock()
    kicad.is_available.return_value = False

    stage = LayoutStage(llm=llm, kicad=kicad)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result.passed is True
    assert any(v.code == "DRC_UNAVAILABLE" for v in result.verifier_result.violations)


@pytest.mark.asyncio
async def test_s4_requires_schematic(tmp_path: Path) -> None:
    state = DesignState()
    stage = LayoutStage(llm=_mock_llm(SAMPLE_PLACEMENTS))
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="S4 requires"):
        await stage.run(state, ctx)


@pytest.mark.asyncio
async def test_s4_raises_when_netlist_missing(tmp_path: Path) -> None:
    state = DesignState(
        schematic=SchematicArtifact(netlist_path=str(tmp_path / "missing.net"))
    )
    stage = LayoutStage(llm=_mock_llm(SAMPLE_PLACEMENTS))
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="not found"):
        await stage.run(state, ctx)


@pytest.mark.asyncio
async def test_s4_full_happy_path_mocked(tmp_path: Path) -> None:
    """Full S4 run with all adapters mocked — DRC clean → state.pcb populated."""
    state, netlist = _state_with_netlist(tmp_path)
    llm = _mock_llm(SAMPLE_PLACEMENTS)

    # Create fake artifacts that the mocked adapters 'produce'
    pcb_path  = tmp_path / "s4_layout" / "board.kicad_pcb"
    dsn_path  = tmp_path / "s4_layout" / "board.dsn"
    ses_path  = tmp_path / "s4_layout" / "board.ses"
    step_path = tmp_path / "s4_layout" / "board.step"
    drc_path  = tmp_path / "s4_layout" / "drc_report.json"
    (tmp_path / "s4_layout").mkdir(parents=True, exist_ok=True)

    drc_path.write_text(SAMPLE_DRC_CLEAN, encoding="utf-8")
    for p in (pcb_path, dsn_path, ses_path, step_path):
        p.write_text("placeholder", encoding="utf-8")

    kicad = MagicMock()
    kicad.is_available.return_value = True
    kicad.run_placement_script.return_value = None
    kicad.export_dsn.return_value = dsn_path
    kicad.import_ses.return_value = pcb_path
    kicad.run_drc.return_value = drc_path
    kicad.export_step.return_value = step_path

    freerouting = MagicMock()
    freerouting.is_available.return_value = True
    freerouting.route.return_value = ses_path

    stage = LayoutStage(llm=llm, kicad=kicad, freerouting=freerouting)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result.passed is True
    assert result.state.pcb is not None
    assert result.state.pcb.board_step_path is not None
    assert result.state.pcb.drc_result is not None


@pytest.mark.asyncio
async def test_s4_drc_failure_propagates(tmp_path: Path) -> None:
    """DRC errors (not just warnings) result in passed=False."""
    state, _ = _state_with_netlist(tmp_path)
    llm = _mock_llm(SAMPLE_PLACEMENTS)

    pcb_path = tmp_path / "s4_layout" / "board.kicad_pcb"
    drc_path = tmp_path / "s4_layout" / "drc_report.json"
    dsn_path = tmp_path / "s4_layout" / "board.dsn"
    ses_path = tmp_path / "s4_layout" / "board.ses"
    (tmp_path / "s4_layout").mkdir(parents=True, exist_ok=True)

    drc_path.write_text(SAMPLE_DRC_ERRORS, encoding="utf-8")
    for p in (pcb_path, dsn_path, ses_path):
        p.write_text("placeholder", encoding="utf-8")

    kicad = MagicMock()
    kicad.is_available.return_value = True
    kicad.run_placement_script.return_value = None
    kicad.export_dsn.return_value = dsn_path
    kicad.import_ses.return_value = pcb_path
    kicad.run_drc.return_value = drc_path
    from mandrel.adapters.kicad import KiCadCLIError
    kicad.export_step.side_effect = KiCadCLIError("step export not available")

    freerouting = MagicMock()
    freerouting.is_available.return_value = True
    freerouting.route.return_value = ses_path

    stage = LayoutStage(llm=llm, kicad=kicad, freerouting=freerouting)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result.passed is False
    assert any(v.severity == "error" for v in result.verifier_result.violations)


# ── overlap resolver ──────────────────────────────────────────────────────────


def test_resolve_overlaps_eliminates_overlaps():
    import itertools
    from mandrel.pipeline.s4_layout import _resolve_overlaps
    comps = [{"ref": f"U{i}", "size_mm": [7.0, 7.0]} for i in range(1, 4)]
    placements = [{"ref": "U1", "x_mm": 25, "y_mm": 15},
                  {"ref": "U2", "x_mm": 26, "y_mm": 15},
                  {"ref": "U3", "x_mm": 27, "y_mm": 15}]
    keep_in = (11.0, 2.0, 48.8, 20.86)
    _resolve_overlaps(placements, comps, keep_in, fixed_refs=set())
    size = {c["ref"]: c["size_mm"] for c in comps}
    pos = {p["ref"]: (p["x_mm"], p["y_mm"]) for p in placements}
    for a, b in itertools.combinations(pos, 2):
        sa, sb = size[a], size[b]
        gap = max(abs(pos[a][0] - pos[b][0]) - (sa[0] + sb[0]) / 2,
                  abs(pos[a][1] - pos[b][1]) - (sa[1] + sb[1]) / 2)
        assert gap >= 0.5 - 1e-6, f"{a}/{b} still overlap"


def test_resolve_overlaps_keeps_fixed_part_put():
    from mandrel.pipeline.s4_layout import _resolve_overlaps
    comps = [{"ref": "J1", "size_mm": [9.0, 9.0]}, {"ref": "U1", "size_mm": [7.0, 7.0]}]
    placements = [{"ref": "J1", "x_mm": 6.0, "y_mm": 11.43},
                  {"ref": "U1", "x_mm": 7.0, "y_mm": 11.43}]
    _resolve_overlaps(placements, comps, (11.0, 2.0, 48.8, 20.86), fixed_refs={"J1"})
    j1 = next(p for p in placements if p["ref"] == "J1")
    assert j1["x_mm"] == 6.0 and j1["y_mm"] == 11.43   # fixed part did not move
