"""Tests for S6 BOM/sourcing stage and supporting components."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mandrel.core.state import (
    Architecture,
    Block,
    CostedBom,
    DesignState,
    DistributorRef,
    Part,
    ProductSpec,
)
from mandrel.core.workflow import Context
from mandrel.pipeline.s6_bom import BomStage
from mandrel.sourcing.stub import StubDistributorClient
from mandrel.verify.bom import BomVerifier

# ── StubDistributorClient ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_grounds_known_mpn() -> None:
    client = StubDistributorClient()
    part = Part(mpn="RP2040")
    grounded = await client.ground_part(part)
    assert grounded.in_stock is True
    assert len(grounded.distributor_refs) == 1
    assert grounded.unit_price_usd is not None


@pytest.mark.asyncio
async def test_stub_refuses_unavailable_mpn() -> None:
    client = StubDistributorClient()
    part = Part(mpn="PART-UNAVAILABLE-XYZ")
    with pytest.raises(ValueError, match="unavailable"):
        await client.ground_part(part)


@pytest.mark.asyncio
async def test_stub_search_returns_empty_when_out_of_stock() -> None:
    client = StubDistributorClient(always_in_stock=False)
    refs = await client.search("RP2040")
    assert refs == []


# ── BomVerifier ───────────────────────────────────────────────────────────────


def _grounded_part(mpn: str = "RP2040") -> Part:
    return Part(
        mpn=mpn,
        in_stock=True,
        distributor_refs=[DistributorRef(distributor="stub", sku=f"SKU-{mpn}", stock_qty=100)],
        unit_price_usd=1.50,
    )


def test_verifier_passes_all_grounded():
    bom = CostedBom(
        lines=[],
        sourcing_verified=True,
    )
    result = BomVerifier().check(bom)
    assert result.passed is True
    assert result.violations == []


def test_verifier_passes_with_stub_warning():
    bom = CostedBom(lines=[], sourcing_verified=False)
    result = BomVerifier().check(bom)
    # Warning only — no errors, so passed=True
    assert result.passed is True
    assert any(v.code == "SOURCING_NOT_VERIFIED" for v in result.violations)
    assert all(v.severity == "warning" for v in result.violations)


def test_verifier_fails_out_of_stock_part():
    from mandrel.core.state import BomLine
    bom = CostedBom(
        lines=[BomLine(part=Part(mpn="RARE-CHIP", in_stock=False), quantity=1)],
        sourcing_verified=True,
    )
    result = BomVerifier().check(bom)
    assert result.passed is False
    assert any(v.code == "PART_OUT_OF_STOCK" for v in result.violations)


def test_verifier_fails_ungrounded_part():
    from mandrel.core.state import BomLine
    bom = CostedBom(
        lines=[BomLine(
            part=Part(mpn="GHOST-123", in_stock=True, distributor_refs=[]),
            quantity=1,
        )],
        sourcing_verified=True,
    )
    result = BomVerifier().check(bom)
    assert result.passed is False
    assert any(v.code == "PART_NOT_GROUNDED" for v in result.violations)


# ── BomStage ──────────────────────────────────────────────────────────────────


def _arch_with_mpns() -> Architecture:
    return Architecture(blocks=[
        Block(id="mcu",  label="RP2040 MCU",  proposed_mpn="SC0914(7)"),
        Block(id="ldo",  label="3.3V LDO",    proposed_mpn="MIC5219-3.3YM5"),
        Block(id="usbc", label="USB-C",        proposed_mpn=None),  # no MPN → skipped
    ])


@pytest.mark.asyncio
async def test_s6_grounds_active_parts(tmp_path: Path) -> None:
    """S6 grounds blocks with proposed_mpn; skips blocks without."""
    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=_arch_with_mpns(),
    )
    stage = BomStage(client=StubDistributorClient())
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    bom = result.state.bom
    assert bom is not None
    # 2 blocks with proposed_mpn → 2 BOM lines
    assert len(bom.lines) == 2
    assert all(ln.part.in_stock for ln in bom.lines)


@pytest.mark.asyncio
async def test_s6_writes_bom_json(tmp_path: Path) -> None:
    """S6 persists bom.json to the output directory."""
    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=_arch_with_mpns(),
    )
    stage = BomStage(client=StubDistributorClient())
    ctx = Context(project_dir=tmp_path)

    await stage.run(state, ctx)

    bom_file = tmp_path / "s6_bom" / "bom.json"
    assert bom_file.exists()
    data = json.loads(bom_file.read_text())
    assert "lines" in data


@pytest.mark.asyncio
async def test_s6_marks_sourcing_unverified_for_stub(tmp_path: Path) -> None:
    """BOM is marked sourcing_verified=False when stub client is used."""
    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=_arch_with_mpns(),
    )
    stage = BomStage(client=StubDistributorClient())
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.state.bom.sourcing_verified is False
    # Stage still passes (warning, not error)
    assert result.verifier_result.passed is True


@pytest.mark.asyncio
async def test_s6_records_grounding_failure(tmp_path: Path) -> None:
    """S6 records GROUNDING_FAILED violation when a part can't be resolved."""
    stub = StubDistributorClient()
    # Override ground_part to raise for one specific MPN
    original_ground = stub.ground_part

    async def patched(part: Part) -> Part:
        if "SC0914" in part.mpn:
            raise ValueError("Simulated API failure")
        return await original_ground(part)

    stub.ground_part = patched

    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=_arch_with_mpns(),
    )
    stage = BomStage(client=stub)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result.passed is False
    assert any(v.code == "GROUNDING_FAILED" for v in result.verifier_result.violations)


@pytest.mark.asyncio
async def test_s6_requires_architecture(tmp_path: Path) -> None:
    """S6 raises ValueError when state.architecture is None."""
    state = DesignState()
    stage = BomStage(client=StubDistributorClient())
    ctx = Context(project_dir=tmp_path)

    with pytest.raises(ValueError, match="S6 requires state.architecture"):
        await stage.run(state, ctx)


@pytest.mark.asyncio
async def test_s6_total_cost_is_sum_of_in_stock_parts(tmp_path: Path) -> None:
    """CostedBom.total_cost_usd is the sum of unit prices for in-stock lines."""
    state = DesignState(
        spec=ProductSpec(raw_brief="b", title="T", description="D"),
        architecture=_arch_with_mpns(),
    )
    stage = BomStage(client=StubDistributorClient())
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    bom = result.state.bom
    expected = sum(
        ln.part.unit_price_usd or 0.0
        for ln in bom.lines
        if ln.part.in_stock
    )
    assert bom.total_cost_usd == pytest.approx(expected)
