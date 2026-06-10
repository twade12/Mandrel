"""Adafruit Feather form factor specification.

All measurements in millimetres unless otherwise noted.
Source: https://learn.adafruit.com/adafruit-feather/feather-specification
"""

from __future__ import annotations

# ── Board outline ─────────────────────────────────────────────────────────────

BOARD_LENGTH_MM: float = 50.8    # 2.0"
BOARD_WIDTH_MM: float  = 22.86   # 0.9"
BOARD_THICKNESS_MM: float = 1.6  # standard 2-layer FR4

# ── Mounting holes (M2.5, 2.0 mm drill) ──────────────────────────────────────
# Coordinates measured from the board's lower-left corner.

MOUNT_HOLE_DRILL_MM: float = 2.0
MOUNT_HOLES_MM: list[tuple[float, float]] = [
    (2.54,                   2.54),                    # lower-left
    (BOARD_LENGTH_MM - 2.54, 2.54),                    # lower-right
    (2.54,                   BOARD_WIDTH_MM - 2.54),   # upper-left
    (BOARD_LENGTH_MM - 2.54, BOARD_WIDTH_MM - 2.54),   # upper-right
]

# ── USB-C connector (at the short end, x = 0) ────────────────────────────────

USB_C_WIDTH_MM: float    = 8.94   # connector body width
USB_C_HEIGHT_MM: float   = 3.26   # connector height above PCB surface
USB_C_OVERHANG_MM: float = 1.5    # how far it overhangs the board edge

# ── JST PH 2.0 (LiPo) ────────────────────────────────────────────────────────

JST_WIDTH_MM: float  = 5.5
JST_HEIGHT_MM: float = 4.0

# ── Pin headers (2.54 mm pitch) ───────────────────────────────────────────────

HEADER_LEFT_PINS: int = 12   # bottom long edge
HEADER_RIGHT_PINS: int = 16  # top long edge
HEADER_PITCH_MM: float = 2.54

# ── Recommended enclosure parameters ─────────────────────────────────────────

ENCLOSURE_WALL_MM: float = 2.0
ENCLOSURE_CLEARANCE_MM: float = 0.5      # board-to-wall air gap
ENCLOSURE_LID_CLEARANCE_MM: float = 8.0  # clearance above tallest SMD component

# Derived enclosure cavity (just the inner volume the board sits in)
ENCLOSURE_CAVITY_L_MM: float = BOARD_LENGTH_MM + 2 * ENCLOSURE_CLEARANCE_MM
ENCLOSURE_CAVITY_W_MM: float = BOARD_WIDTH_MM  + 2 * ENCLOSURE_CLEARANCE_MM
ENCLOSURE_CAVITY_H_MM: float = BOARD_THICKNESS_MM + ENCLOSURE_LID_CLEARANCE_MM


def mount_holes_centered() -> list[tuple[float, float]]:
    """Return mount-hole positions in board-centre coordinates (build123d origin)."""
    cx = BOARD_LENGTH_MM / 2
    cy = BOARD_WIDTH_MM / 2
    return [(x - cx, y - cy) for x, y in MOUNT_HOLES_MM]


def check_outline(length_mm: float, width_mm: float, tol_mm: float = 0.1) -> list[str]:
    """Return a list of violation strings if dimensions are outside tolerance."""
    violations: list[str] = []
    if abs(length_mm - BOARD_LENGTH_MM) > tol_mm:
        violations.append(
            f"Board length {length_mm:.3f} mm ≠ {BOARD_LENGTH_MM} mm "
            f"(Δ={abs(length_mm - BOARD_LENGTH_MM):.3f} mm, tol={tol_mm})"
        )
    if abs(width_mm - BOARD_WIDTH_MM) > tol_mm:
        violations.append(
            f"Board width {width_mm:.3f} mm ≠ {BOARD_WIDTH_MM} mm "
            f"(Δ={abs(width_mm - BOARD_WIDTH_MM):.3f} mm, tol={tol_mm})"
        )
    return violations
