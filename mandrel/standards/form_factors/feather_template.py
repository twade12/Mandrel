"""Deterministic Feather board template.

The Adafruit Feather is a fixed mechanical standard, so the board outline
(rounded corners), mounting holes, and the USB-C edge placement/rotation are
*not* LLM decisions — they are emitted deterministically here. The LLM only
places free interior components into the keep-in rectangle.

This module produces pcbnew source text (injected into the S4 placement script,
which runs under the KiCad Python interpreter — GPL boundary preserved) plus
pure-Python helpers the stage uses to constrain and override LLM placement.

Constants verified against KiCad 9.0.9 footprint libraries and live renders:
  - corner radius 3.0 mm closes into a valid Edge.Cuts solid (STEP export)
  - USB-C GCT USB4105 horizontal at the left short edge needs rotation 270°
    for the receptacle mouth to face off-board (90° faces inboard — wrong)
"""

from __future__ import annotations

from .feather import (
    BOARD_LENGTH_MM,
    BOARD_WIDTH_MM,
    MOUNT_HOLES_MM,
)

CORNER_RADIUS_MM: float = 3.0
EDGE_MARGIN_MM: float = 2.0
# USB-C occupies the left short edge; interior parts start to its right.
USB_C_ZONE_X_MM: float = 11.0
USB_C_ORIGIN_X_MM: float = 6.0          # body fully on-board, pads clear of edge
USB_C_EDGE_ROTATION_DEG: float = 270.0  # mouth faces off the left short edge

MOUNT_HOLE_FOOTPRINT = ("MountingHole", "MountingHole_2.7mm_M2.5")


def keep_in_rect(
    board_l_mm: float = BOARD_LENGTH_MM,
    board_w_mm: float = BOARD_WIDTH_MM,
) -> tuple[float, float, float, float]:
    """Interior rectangle (x_min, y_min, x_max, y_max) the LLM may place into.

    Excludes the USB-C zone on the left and a margin from every edge so parts
    compact into the real usable area instead of sprawling across the board.
    """
    return (
        USB_C_ZONE_X_MM,
        EDGE_MARGIN_MM,
        board_l_mm - EDGE_MARGIN_MM,
        board_w_mm - EDGE_MARGIN_MM,
    )


def usb_c_fixed_placements(
    components: list[dict],
    board_w_mm: float = BOARD_WIDTH_MM,
) -> dict[str, dict]:
    """Map each USB-C component ref to its locked position/rotation.

    Detected by footprint (Connector:USB_C*). Returned placements override
    whatever the LLM proposes, so the connector always sits correctly oriented
    at the short edge.
    """
    fixed: dict[str, dict] = {}
    for comp in components:
        fp = (comp.get("footprint") or "").upper()
        if "USB_C" in fp:
            fixed[comp["ref"]] = {
                "ref": comp["ref"],
                "x_mm": USB_C_ORIGIN_X_MM,
                "y_mm": board_w_mm / 2.0,
                "rotation_deg": USB_C_EDGE_ROTATION_DEG,
                "side": "front",
            }
    return fixed


def outline_and_holes_src(
    board_l_mm: float = BOARD_LENGTH_MM,
    board_w_mm: float = BOARD_WIDTH_MM,
    radius_mm: float = CORNER_RADIUS_MM,
    mount_holes_mm: list[tuple[float, float]] | None = None,
) -> str:
    """pcbnew source drawing the rounded outline + mounting holes.

    Injected into the placement script after `board = pcbnew.BOARD()`. Assumes
    `board` and `FP_LIB_DIR` are already in scope. Contains NO brace characters
    so it survives str.format of the surrounding template (it is inserted via
    a marker replace, but this keeps it format-safe regardless).
    """
    holes = mount_holes_mm if mount_holes_mm is not None else MOUNT_HOLES_MM
    lib, name = MOUNT_HOLE_FOOTPRINT
    holes_src = "\n".join(
        f"_add_mounting_hole({x}, {y}, {i + 1})"
        for i, (x, y) in enumerate(holes)
    )
    return f"""\
import math as _math

# ── Rounded board outline (deterministic Feather template) ──────────────────
_OL_L, _OL_W, _OL_R = {board_l_mm}, {board_w_mm}, {radius_mm}

def _edge_line(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
    board.Add(s)

def _edge_arc(cx, cy, sx, sy, ex, ey, r):
    # Midpoint via the vector-sum bisector of the start/end directions, so the
    # arc always bulges OUTWARD. Averaging the two atan2 angles wraps at the
    # +/-pi boundary and flips one corner inward (the H1 edge-cut defect).
    sdx, sdy = sx - cx, sy - cy
    edx, edy = ex - cx, ey - cy
    bx, by = sdx + edx, sdy + edy
    blen = _math.hypot(bx, by)
    if blen < 1e-9:  # degenerate (antipodal) — fall back to a perpendicular
        bx, by, blen = -sdy, sdx, r
    mx = cx + r * bx / blen
    my = cy + r * by / blen
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_ARC)
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetArcGeometry(
        pcbnew.VECTOR2I(pcbnew.FromMM(sx), pcbnew.FromMM(sy)),
        pcbnew.VECTOR2I(pcbnew.FromMM(mx), pcbnew.FromMM(my)),
        pcbnew.VECTOR2I(pcbnew.FromMM(ex), pcbnew.FromMM(ey)),
    )
    board.Add(s)

_edge_line(_OL_R, 0, _OL_L - _OL_R, 0)
_edge_arc(_OL_L - _OL_R, _OL_R, _OL_L - _OL_R, 0, _OL_L, _OL_R, _OL_R)
_edge_line(_OL_L, _OL_R, _OL_L, _OL_W - _OL_R)
_edge_arc(_OL_L - _OL_R, _OL_W - _OL_R, _OL_L, _OL_W - _OL_R, _OL_L - _OL_R, _OL_W, _OL_R)
_edge_line(_OL_L - _OL_R, _OL_W, _OL_R, _OL_W)
_edge_arc(_OL_R, _OL_W - _OL_R, _OL_R, _OL_W, 0, _OL_W - _OL_R, _OL_R)
_edge_line(0, _OL_W - _OL_R, 0, _OL_R)
_edge_arc(_OL_R, _OL_R, 0, _OL_R, _OL_R, 0, _OL_R)

# ── Mounting holes ──────────────────────────────────────────────────────────
def _add_mounting_hole(x, y, n):
    mh = pcbnew.FootprintLoad(FP_LIB_DIR + "/{lib}.pretty", "{name}")
    if mh is None:
        print("WARN: mounting hole footprint not found", file=sys.stderr)
        return
    mh.SetReference("H" + str(n))
    mh.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    board.Add(mh)

{holes_src}
"""
