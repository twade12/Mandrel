"""Tests for S1 intent-capture stage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mandrel.core.state import Constraints, DesignState, FormFactor, ProductSpec
from mandrel.core.workflow import Context
from mandrel.pipeline.s1_intent import IntentStage, _extract_json, _parse_spec

# ── Unit tests — no LLM or network required ───────────────────────────────────


def test_extract_json_plain():
    text = '{"title": "Sensor Board", "functions": ["temp"]}'
    data = _extract_json(text)
    assert data["title"] == "Sensor Board"


def test_extract_json_strips_markdown_fences():
    text = "```json\n{\"title\": \"X\"}\n```"
    data = _extract_json(text)
    assert data["title"] == "X"


def test_extract_json_raises_on_missing():
    with pytest.raises(ValueError, match="No JSON object"):
        _extract_json("just some text with no braces")


def test_parse_spec_full():
    raw = json.dumps({
        "title": "Feather Sensor Board",
        "description": "A temperature and motion sensor.",
        "functions": ["temperature sensing", "motion detection"],
        "interfaces": ["USB-C", "I2C"],
        "power": {"supply_voltage_v": 3.3, "max_current_ma": 200, "battery_capacity_mah": None},
        "environment": "indoor 0–70°C",
        "target_cost_usd": None,
        "target_qty": None,
    })
    spec = _parse_spec(raw, raw_brief="brief")
    assert spec.title == "Feather Sensor Board"
    assert "USB-C" in spec.interfaces
    assert spec.power is not None
    assert spec.power.supply_voltage_v == 3.3
    assert spec.power.battery_capacity_mah is None


def test_parse_spec_minimal():
    raw = json.dumps({"title": "Min Board", "description": "desc"})
    spec = _parse_spec(raw, raw_brief="brief")
    assert spec.title == "Min Board"
    assert spec.functions == []


# ── Stage tests — mock LLM ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_s1_extracts_product_spec(tmp_path: Path) -> None:
    """S1 calls LLM and populates state.spec from a structured JSON response."""
    llm_response = json.dumps({
        "title": "Feather Sensor Board",
        "description": "Temperature and motion sensor on Feather form factor.",
        "functions": ["temperature sensing", "motion detection"],
        "interfaces": ["USB-C", "I2C"],
        "power": {"supply_voltage_v": 3.3, "max_current_ma": 200, "battery_capacity_mah": None},
        "environment": "indoor",
        "target_cost_usd": None,
        "target_qty": None,
    })
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=llm_response)

    state = DesignState(
        spec=ProductSpec(raw_brief="I need a temp+motion sensor Feather board"),
        constraints=Constraints(form_factor=FormFactor.FEATHER),
    )
    stage = IntentStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.state.spec is not None
    assert result.state.spec.title == "Feather Sensor Board"
    assert "USB-C" in result.state.spec.interfaces
    assert "I2C" in result.state.spec.interfaces
    assert result.state.spec.power is not None
    assert result.verifier_result is not None
    assert result.verifier_result.passed is True
    # raw_brief is preserved
    assert result.state.spec.raw_brief == "I need a temp+motion sensor Feather board"


@pytest.mark.asyncio
async def test_s1_raises_without_raw_brief(tmp_path: Path) -> None:
    """S1 raises ValueError if no raw_brief is set on the state."""
    mock_llm = AsyncMock()
    state = DesignState()  # spec is None
    stage = IntentStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="raw_brief"):
        await stage.run(state, ctx)


@pytest.mark.asyncio
async def test_s1_handles_markdown_fenced_json(tmp_path: Path) -> None:
    """S1 handles LLMs that wrap JSON in markdown code fences."""
    llm_response = '```json\n{"title": "Wrapped Board", "description": "d"}\n```'
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=llm_response)

    state = DesignState(spec=ProductSpec(raw_brief="a brief"))
    stage = IntentStage(llm=mock_llm)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)
    assert result.state.spec.title == "Wrapped Board"
