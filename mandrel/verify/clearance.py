"""Enclosure clearance / fit verifier.

Phase 1: bounding-box check only — verifies that the board dimensions fit inside
the enclosure cavity with the required air gap on every axis.

Phase 3 will replace this with full 3-D interference detection using build123d's
boolean operations on the actual STEP geometry.
"""

from __future__ import annotations

from typing import Any

from mandrel.core.state import VerifierResult, Violation


class ClearanceVerifier:
    """Check that a board fits inside an enclosure cavity with the required clearance."""

    def __init__(self, min_clearance_mm: float = 0.5) -> None:
        self.min_clearance_mm = min_clearance_mm

    def check_dimensions(
        self,
        board_l: float,
        board_w: float,
        board_h: float,
        cavity_l: float,
        cavity_w: float,
        cavity_h: float,
    ) -> VerifierResult:
        """Return a VerifierResult comparing board dims to enclosure cavity dims."""
        violations: list[Violation] = []

        axes = [
            ("length", board_l, cavity_l),
            ("width",  board_w, cavity_w),
            ("height", board_h, cavity_h),
        ]
        for label, board_d, cavity_d in axes:
            gap = cavity_d - board_d
            if gap < self.min_clearance_mm:
                violations.append(Violation(
                    code="CLEARANCE_FAIL",
                    message=(
                        f"Enclosure {label}: cavity={cavity_d:.2f} mm, "
                        f"board={board_d:.2f} mm, gap={gap:.2f} mm "
                        f"(min {self.min_clearance_mm} mm required)"
                    ),
                    severity="error",
                    location=label,
                ))

        return VerifierResult(
            passed=len(violations) == 0,
            score=1.0 if not violations else 0.0,
            violations=violations,
        )

    def check(self, artifact: Any, against: Any = None) -> VerifierResult:
        """Protocol-compatible entry point.

        artifact:  (board_l, board_w, board_h) tuple
        against:   (cavity_l, cavity_w, cavity_h) tuple
        """
        if not (isinstance(artifact, tuple) and isinstance(against, tuple)):
            return VerifierResult(
                passed=False,
                score=0.0,
                violations=[Violation(
                    code="CLEARANCE_TYPE_ERROR",
                    message="artifact and against must be (l, w, h) tuples",
                    severity="error",
                )],
            )
        return self.check_dimensions(*artifact, *against)
