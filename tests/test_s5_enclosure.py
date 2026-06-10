"""Tests for S5 enclosure-generation stage and supporting components."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mandrel.core.state import CadArtifact, Constraints, DesignState, FormFactor
from mandrel.core.workflow import Context
from mandrel.pipeline.s5_enclosure import EnclosureStage
from mandrel.standards.form_factors import feather
from mandrel.verify.clearance import ClearanceVerifier

# ── Feather spec constants ────────────────────────────────────────────────────


def test_feather_board_dimensions():
    assert feather.BOARD_LENGTH_MM == pytest.approx(50.8)
    assert feather.BOARD_WIDTH_MM  == pytest.approx(22.86)


def test_feather_has_four_mount_holes():
    assert len(feather.MOUNT_HOLES_MM) == 4


def test_feather_mount_holes_centered_origin():
    """Centred coordinates should be symmetric around (0, 0)."""
    holes = feather.mount_holes_centered()
    xs = [x for x, _ in holes]
    ys = [y for _, y in holes]
    assert min(xs) == pytest.approx(-max(xs), abs=1e-9)
    assert min(ys) == pytest.approx(-max(ys), abs=1e-9)


def test_feather_check_outline_pass():
    violations = feather.check_outline(50.8, 22.86)
    assert violations == []


def test_feather_check_outline_fail():
    violations = feather.check_outline(55.0, 22.86)
    assert len(violations) == 1
    assert "length" in violations[0]


# ── Clearance verifier ────────────────────────────────────────────────────────


def test_clearance_passes_when_cavity_larger():
    v = ClearanceVerifier(min_clearance_mm=0.5)
    result = v.check_dimensions(
        board_l=50.8, board_w=22.86, board_h=1.6,
        cavity_l=52.0, cavity_w=24.0, cavity_h=10.0,
    )
    assert result.passed is True
    assert result.violations == []


def test_clearance_fails_when_cavity_too_small():
    v = ClearanceVerifier(min_clearance_mm=0.5)
    result = v.check_dimensions(
        board_l=50.8, board_w=22.86, board_h=1.6,
        cavity_l=51.0,   # only 0.2 mm gap < 0.5 mm required
        cavity_w=24.0,
        cavity_h=10.0,
    )
    assert result.passed is False
    assert any("length" in v.location for v in result.violations)


def test_clearance_feather_default_enclosure_passes():
    """The default Feather enclosure dimensions must pass clearance for the Feather board."""
    v = ClearanceVerifier(min_clearance_mm=0.5)
    result = v.check_dimensions(
        board_l=feather.BOARD_LENGTH_MM,
        board_w=feather.BOARD_WIDTH_MM,
        board_h=feather.BOARD_THICKNESS_MM,
        cavity_l=feather.ENCLOSURE_CAVITY_L_MM,
        cavity_w=feather.ENCLOSURE_CAVITY_W_MM,
        cavity_h=feather.ENCLOSURE_CAVITY_H_MM,
    )
    assert result.passed is True


# ── S5 stage tests — mock build123d adapter ───────────────────────────────────


@pytest.mark.asyncio
async def test_s5_feather_clearance_passes(tmp_path: Path) -> None:
    """S5 records a passing clearance result for a standard Feather board."""
    mock_cad = MagicMock()
    board_step = tmp_path / "feather_board.step"
    board_step.touch()
    enc_step   = tmp_path / "feather_enclosure.step"
    enc_step.touch()
    mock_cad.generate_feather_board_step.return_value = board_step
    mock_cad.generate_feather_enclosure_step.return_value = enc_step

    state = DesignState(constraints=Constraints(form_factor=FormFactor.FEATHER))
    stage = EnclosureStage(cad=mock_cad)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result is not None
    assert result.verifier_result.passed is True
    assert result.state.enclosure is not None
    assert result.state.enclosure.step_path is not None


@pytest.mark.asyncio
async def test_s5_records_enclosure_artifact(tmp_path: Path) -> None:
    """S5 populates state.enclosure with the generated STEP path."""
    mock_cad = MagicMock()
    enc_step = tmp_path / "feather_enclosure.step"
    enc_step.touch()
    mock_cad.generate_feather_board_step.return_value = tmp_path / "board.step"
    mock_cad.generate_feather_enclosure_step.return_value = enc_step

    state = DesignState(constraints=Constraints(form_factor=FormFactor.FEATHER))
    stage = EnclosureStage(cad=mock_cad)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert isinstance(result.state.enclosure, CadArtifact)
    assert result.state.enclosure.step_path == str(enc_step)


@pytest.mark.asyncio
async def test_s5_handles_cad_error(tmp_path: Path) -> None:
    """S5 returns a failed VerifierResult when build123d raises."""
    from mandrel.adapters.cad import CADError

    mock_cad = MagicMock()
    mock_cad.generate_feather_board_step.return_value = None
    mock_cad.generate_feather_enclosure_step.side_effect = CADError("build123d not installed")

    state = DesignState(constraints=Constraints(form_factor=FormFactor.FEATHER))
    stage = EnclosureStage(cad=mock_cad)
    ctx = Context(project_dir=tmp_path)

    result = await stage.run(state, ctx)

    assert result.verifier_result.passed is False
    assert any("ENCLOSURE_GEN_FAILED" in v.code for v in result.verifier_result.violations)
