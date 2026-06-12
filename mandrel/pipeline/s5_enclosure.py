"""S5 — Enclosure / fixture: board STEP → build123d enclosure → clearance check.

Flow:
  1. If state.pcb has a board_step_path, use it; otherwise generate a parametric
     Feather board STEP from the known form-factor dimensions (Phase 1 path —
     S4/PCB layout hasn't run yet).
  2. Build123dAdapter generates a box enclosure around the board.
  3. ClearanceVerifier checks that the board fits inside the cavity with the
     required air gap.
  4. Human checkpoint fires for fit review.

Phase 1 simplification: bounding-box clearance only (no 3-D interference detection).
Phase 3 will add full STEP boolean interference checking.
"""

from __future__ import annotations

from pathlib import Path

from mandrel.adapters.cad import Build123dAdapter, CADError
from mandrel.core.state import CadArtifact, DesignState, FormFactor, VerifierResult, Violation
from mandrel.core.workflow import Context, StageResult
from mandrel.verify.clearance import ClearanceVerifier


class EnclosureStage:
    """S5: generate enclosure STEP and verify clearance against the board."""

    name = "s5_enclosure"

    def __init__(
        self,
        cad: Build123dAdapter | None = None,
        clearance_verifier: ClearanceVerifier | None = None,
        wall_mm: float = 2.0,
        clearance_mm: float = 0.5,
        lid_clearance_mm: float = 8.0,
    ) -> None:
        self._cad         = cad or Build123dAdapter()
        self._clearance   = clearance_verifier or ClearanceVerifier(min_clearance_mm=clearance_mm)
        self._wall        = wall_mm
        self._clearance_mm = clearance_mm
        self._lid_h       = lid_clearance_mm

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        output_dir = ctx.project_dir / "s5_enclosure"
        output_dir.mkdir(parents=True, exist_ok=True)

        form_factor = state.constraints.form_factor if state.constraints else FormFactor.CUSTOM

        # Graceful degradation: build123d needs Python ≤ 3.13 (cadquery-ocp
        # wheels). Without it, warn and continue so the spine stays runnable.
        if not self._cad.is_available():
            return StageResult(
                state=state,
                artifacts=[],
                verifier_result=VerifierResult(
                    passed=True,
                    score=0.5,
                    violations=[Violation(
                        code="ENCLOSURE_UNAVAILABLE",
                        message="S5 skipped: build123d is not installed in this "
                                "interpreter (requires Python ≤ 3.13). "
                                "Install with: uv sync --extra cad",
                        severity="warning",
                    )],
                ),
            )

        # 1. Obtain board STEP
        board_step = _get_board_step(state, ctx, self._cad, output_dir, form_factor)

        # 2. Generate enclosure
        try:
            enc_step = self._cad.generate_feather_enclosure_step(
                output_dir=output_dir,
                wall_mm=self._wall,
                clearance_mm=self._clearance_mm,
                lid_clearance_mm=self._lid_h,
            )
        except CADError as exc:
            return StageResult(
                state=state,
                artifacts=[board_step] if board_step else [],
                verifier_result=VerifierResult(
                    passed=False,
                    violations=[Violation(
                        code="ENCLOSURE_GEN_FAILED",
                        message=str(exc),
                        severity="error",
                    )],
                ),
            )

        # 3. Clearance check (bounding-box, Phase 1)
        clearance_result = _check_clearance(
            form_factor, self._clearance, self._clearance_mm, self._lid_h
        )

        artifacts = [p for p in [board_step, enc_step] if p and p.exists()]
        new_state = state.model_copy(update={
            "enclosure": CadArtifact(
                step_path=str(enc_step),
                script_path=str(output_dir / "_cad_gen.py"),
                clearance_result=clearance_result,
            )
        })
        return StageResult(
            state=new_state,
            artifacts=artifacts,
            verifier_result=clearance_result,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_board_step(
    state: DesignState,
    ctx: Context,
    cad: Build123dAdapter,
    output_dir: Path,
    form_factor: FormFactor,
) -> Path | None:
    """Return the board STEP path: from state.pcb if available, else parametric."""
    if state.pcb and state.pcb.board_step_path:
        path = Path(state.pcb.board_step_path)
        if path.exists():
            return path

    if form_factor == FormFactor.FEATHER:
        try:
            return cad.generate_feather_board_step(output_dir)
        except CADError:
            return None
    return None


def _check_clearance(
    form_factor: FormFactor,
    verifier: ClearanceVerifier,
    clearance_mm: float,
    lid_clearance_mm: float,
) -> VerifierResult:
    """Run bounding-box clearance check for the given form factor."""
    if form_factor == FormFactor.FEATHER:
        from mandrel.standards.form_factors.feather import (
            BOARD_LENGTH_MM,
            BOARD_THICKNESS_MM,
            BOARD_WIDTH_MM,
            ENCLOSURE_CAVITY_L_MM,
            ENCLOSURE_CAVITY_W_MM,
        )
        cavity_h = BOARD_THICKNESS_MM + lid_clearance_mm
        return verifier.check_dimensions(
            board_l=BOARD_LENGTH_MM,
            board_w=BOARD_WIDTH_MM,
            board_h=BOARD_THICKNESS_MM,
            cavity_l=ENCLOSURE_CAVITY_L_MM,
            cavity_w=ENCLOSURE_CAVITY_W_MM,
            cavity_h=cavity_h,
        )
    # For other form factors in Phase 1, return a warning (not implemented yet)
    return VerifierResult(
        passed=True,
        score=0.5,
        violations=[Violation(
            code="CLEARANCE_FORM_FACTOR_UNSUPPORTED",
            message=f"Clearance check not yet implemented for {form_factor}; skipped.",
            severity="warning",
        )],
    )
