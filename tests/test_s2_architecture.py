"""Tests for S2 architecture stage and supporting components."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mandrel.core.state import (
    Architecture,
    Block,
    Connection,
    Constraints,
    DesignState,
    FormFactor,
    ProductSpec,
)
from mandrel.core.workflow import Context
from mandrel.pipeline.s2_architecture import ArchitectureStage, _extract_json, _parse_architecture
from mandrel.verify.architecture import ArchitectureVerifier

# ── _extract_json helper ──────────────────────────────────────────────────────


def test_extract_json_plain():
    text = '{"blocks": [], "connections": []}'
    data = _extract_json(text)
    assert data["blocks"] == []


def test_extract_json_strips_markdown():
    text = '```json\n{"blocks": [], "connections": []}\n```'
    data = _extract_json(text)
    assert "blocks" in data


def test_extract_json_raises_on_missing():
    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json("no json here")


# ── _parse_architecture helper ────────────────────────────────────────────────


def _sample_arch_json() -> str:
    return json.dumps({
        "blocks": [
            {"id": "mcu", "label": "RP2040 MCU", "proposed_mpn": "SC0914(7)",
             "kicad_lib": "MCU_RaspberryPi_RP2xxx:RP2040"},
            {"id": "ldo", "label": "3.3V LDO", "proposed_mpn": "MIC5219-3.3YM5",
             "kicad_lib": "Regulator_Linear:MIC5219-3.3YM5"},
            {"id": "usbc", "label": "USB-C Receptacle", "proposed_mpn": None,
             "kicad_lib": "Connector_USB:USB_C_Receptacle_USB2.0"},
        ],
        "connections": [
            {"from_block": "usbc", "to_block": "ldo", "signal": "VBUS"},
            {"from_block": "ldo",  "to_block": "mcu", "signal": "+3V3"},
        ],
        "rationale": "RP2040 for native USB. MIC5219 LDO for 3.3V rail.",
    })


def test_parse_architecture_blocks_and_connections():
    arch = _parse_architecture(_sample_arch_json())
    assert len(arch.blocks) == 3
    assert len(arch.connections) == 2
    mcu = next(b for b in arch.blocks if b.id == "mcu")
    assert mcu.proposed_mpn == "SC0914(7)"
    assert mcu.kicad_lib == "MCU_RaspberryPi_RP2xxx:RP2040"


def test_parse_architecture_null_kicad_lib():
    arch = _parse_architecture(_sample_arch_json())
    usbc = next(b for b in arch.blocks if b.id == "usbc")
    assert usbc.proposed_mpn is None


# ── ArchitectureVerifier ──────────────────────────────────────────────────────


def _valid_arch() -> Architecture:
    return Architecture(
        blocks=[
            Block(id="mcu", label="RP2040 MCU"),
            Block(id="ldo", label="3.3V LDO Regulator"),
            Block(id="usbc", label="USB-C"),
        ],
        connections=[
            Connection(from_block="usbc", to_block="ldo", signal="VBUS"),
            Connection(from_block="ldo",  to_block="mcu", signal="+3V3"),
        ],
    )


def test_verifier_passes_valid_arch():
    result = ArchitectureVerifier().check(_valid_arch())
    assert result.passed is True
    assert result.violations == []


def test_verifier_catches_dangling_connection():
    arch = _valid_arch()
    arch.connections.append(Connection(from_block="ghost", to_block="mcu", signal="SPI"))
    result = ArchitectureVerifier().check(arch)
    assert result.passed is False
    assert any(v.code == "DANGLING_CONNECTION" for v in result.violations)


def test_verifier_catches_duplicate_block_id():
    arch = _valid_arch()
    arch.blocks.append(Block(id="mcu", label="Duplicate MCU"))
    result = ArchitectureVerifier().check(arch)
    assert result.passed is False
    assert any(v.code == "DUPLICATE_BLOCK_ID" for v in result.violations)


def test_verifier_warns_no_power_block():
    arch = Architecture(
        blocks=[Block(id="mcu", label="RP2040 MCU"), Block(id="sensor", label="BME280")],
        connections=[Connection(from_block="mcu", to_block="sensor", signal="I2C")],
    )
    result = ArchitectureVerifier().check(arch)
    # Warning only — should still pass (errors = 0)
    assert result.passed is True
    assert any(v.code == "NO_POWER_BLOCK" for v in result.violations)


def test_verifier_errors_no_mcu_block():
    arch = Architecture(
        blocks=[Block(id="ldo", label="3.3V LDO"), Block(id="sensor", label="BME280")],
        connections=[],
    )
    result = ArchitectureVerifier().check(arch)
    assert result.passed is False
    assert any(v.code == "NO_MCU_BLOCK" for v in result.violations)


# ── S2 stage tests — mock LLM ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s2_populates_state_architecture(tmp_path: Path) -> None:
    """S2 calls LLM, parses architecture, stores in state.architecture."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_sample_arch_json())

    state = DesignState(
        spec=ProductSpec(
            raw_brief="brief",
            title="Sensor Board",
            description="A sensor board.",
        ),
        constraints=Constraints(form_factor=FormFactor.FEATHER),
    )
    stage = ArchitectureStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result is not None
    assert result.verifier_result.passed is True
    assert result.state.architecture is not None
    assert len(result.state.architecture.blocks) == 3
    assert len(result.state.architecture.connections) == 2


@pytest.mark.asyncio
async def test_s2_writes_architecture_json(tmp_path: Path) -> None:
    """S2 persists architecture.json to the output directory."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_sample_arch_json())

    state = DesignState(spec=ProductSpec(raw_brief="b", title="T", description="D"))
    stage = ArchitectureStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    await stage.run(state, ctx)

    arch_file = tmp_path / "s2_architecture" / "architecture.json"
    assert arch_file.exists()
    data = json.loads(arch_file.read_text())
    assert "blocks" in data


@pytest.mark.asyncio
async def test_s2_retries_on_structural_violation(tmp_path: Path) -> None:
    """S2 feeds verifier violations back to LLM and retries."""
    bad = json.dumps({
        "blocks": [{"id": "mcu", "label": "MCU", "proposed_mpn": None, "kicad_lib": None}],
        "connections": [
            {"from_block": "ghost", "to_block": "mcu", "signal": "SPI"},
        ],
        "rationale": "bad",
    })
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=[bad, _sample_arch_json()])

    state = DesignState(spec=ProductSpec(raw_brief="b", title="T", description="D"))
    stage = ArchitectureStage(llm=mock_llm, max_retries=2)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert mock_llm.complete.call_count == 2
    assert result.verifier_result.passed is True


@pytest.mark.asyncio
async def test_s2_requires_spec(tmp_path: Path) -> None:
    """S2 raises ValueError when state.spec is None."""
    mock_llm = AsyncMock()
    state = DesignState()
    stage = ArchitectureStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="S2 requires state.spec"):
        await stage.run(state, ctx)


@pytest.mark.asyncio
async def test_s2_block_kicad_lib_propagated_to_state(tmp_path: Path) -> None:
    """Block.kicad_lib from the LLM response is available on the architecture blocks."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_sample_arch_json())

    state = DesignState(spec=ProductSpec(raw_brief="b", title="T", description="D"))
    stage = ArchitectureStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    mcu_block = next(b for b in result.state.architecture.blocks if b.id == "mcu")
    assert mcu_block.kicad_lib == "MCU_RaspberryPi_RP2xxx:RP2040"
