"""Tests for S3 schematic-capture stage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mandrel.core.state import DesignState, ProductSpec
from mandrel.core.workflow import Context
from mandrel.pipeline.s3_schematic import SchematicStage, _strip_markdown
from mandrel.verify.erc import ERCVerifier

# ── Unit tests ────────────────────────────────────────────────────────────────


def test_strip_markdown_removes_fences():
    code = "```python\nfrom skidl import *\n```"
    assert _strip_markdown(code) == "from skidl import *"


def test_strip_markdown_no_fences():
    code = "from skidl import *\ngenerate_netlist()"
    assert _strip_markdown(code) == code


def test_erc_verifier_clean_report(tmp_path: Path) -> None:
    report = tmp_path / "erc.json"
    report.write_text(json.dumps({"errors": 0, "warnings": 0, "items": []}))
    result = ERCVerifier().check(report)
    assert result.passed is True
    assert result.score == 1.0


def test_erc_verifier_with_errors(tmp_path: Path) -> None:
    report = tmp_path / "erc.json"
    report.write_text(json.dumps({
        "errors": 2,
        "warnings": 1,
        "items": [
            {"type": "error", "description": "Pin not connected", "pos": ""},
            {"type": "error", "description": "No power flag", "pos": ""},
            {"type": "warning", "description": "Value differs", "pos": ""},
        ],
    }))
    result = ERCVerifier().check(report)
    assert result.passed is False
    assert len([v for v in result.violations if v.severity == "error"]) == 2


def test_erc_verifier_missing_file(tmp_path: Path) -> None:
    result = ERCVerifier().check(tmp_path / "nonexistent.json")
    assert result.passed is False
    assert result.violations[0].code == "ERC_PARSE_ERROR"


# ── Stage tests — mock LLM + adapters ────────────────────────────────────────


def _make_skidl_script() -> str:
    return "from skidl import *\ngenerate_netlist(filepath='netlist.net')"


@pytest.mark.asyncio
async def test_s3_succeeds_with_clean_erc(tmp_path: Path) -> None:
    """S3 returns passed=True when ERC finds no errors."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_make_skidl_script())

    # SKiDL adapter produces a .kicad_sch file
    mock_skidl = MagicMock()
    sch_path = tmp_path / "schematic.kicad_sch"
    sch_path.touch()
    net_path = tmp_path / "netlist.net"
    net_path.touch()
    mock_skidl.run_script.return_value = {"schematic": sch_path, "netlist": net_path}

    # kicad-cli ERC returns a clean report
    erc_report = tmp_path / "erc_report.json"
    erc_report.write_text(json.dumps({"errors": 0, "warnings": 0, "items": []}))
    mock_kicad = MagicMock()
    mock_kicad.run_erc.return_value = erc_report

    state = DesignState(spec=ProductSpec(
        title="Sensor Board", description="test",
        raw_brief="brief",
    ))
    stage = SchematicStage(
        llm=mock_llm, skidl=mock_skidl, kicad=mock_kicad, max_retries=1
    )
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result is not None
    assert result.verifier_result.passed is True
    assert result.state.schematic is not None
    assert result.state.schematic.erc_result is not None
    assert result.state.schematic.erc_result.passed is True


@pytest.mark.asyncio
async def test_s3_retries_on_erc_failure(tmp_path: Path) -> None:
    """S3 feeds ERC violations back to LLM and retries up to max_retries times."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_make_skidl_script())

    mock_skidl = MagicMock()
    sch_path = tmp_path / "schematic.kicad_sch"
    sch_path.touch()
    mock_skidl.run_script.return_value = {"schematic": sch_path}

    # First call: ERC fails; second call: ERC passes
    fail_report = tmp_path / "erc_fail.json"
    fail_report.write_text(json.dumps({
        "errors": 1, "warnings": 0,
        "items": [{"type": "error", "description": "Pin not connected", "pos": ""}],
    }))
    pass_report = tmp_path / "erc_pass.json"
    pass_report.write_text(json.dumps({"errors": 0, "warnings": 0, "items": []}))
    mock_kicad = MagicMock()
    mock_kicad.run_erc.side_effect = [fail_report, pass_report]

    state = DesignState(spec=ProductSpec(
        title="Sensor Board", description="test", raw_brief="brief"
    ))
    stage = SchematicStage(
        llm=mock_llm, skidl=mock_skidl, kicad=mock_kicad, max_retries=3
    )
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert mock_llm.complete.call_count == 2
    assert result.verifier_result.passed is True


@pytest.mark.asyncio
async def test_s3_requires_spec(tmp_path: Path) -> None:
    """S3 raises ValueError when state.spec is None."""
    mock_llm = AsyncMock()
    state = DesignState()
    stage = SchematicStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="S3 requires state.spec"):
        await stage.run(state, ctx)
