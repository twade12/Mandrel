"""build123d / CadQuery CAD adapter.

build123d is Apache-2.0 and may run in-process, but LLM-generated scripts execute
in a subprocess for safety. Parametric generators (Feather board, box enclosure)
run in-process via the helper methods below.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class CADError(RuntimeError):
    pass


class Build123dAdapter:
    """Runs build123d Python scripts for parametric MCAD generation."""

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout

    def is_available(self) -> bool:
        """True if build123d is importable in the script interpreter."""
        import importlib.util
        return importlib.util.find_spec("build123d") is not None

    # ── Generic script runner ─────────────────────────────────────────────────

    def run_script(self, script: str, output_dir: Path) -> dict[str, Path]:
        """Execute a build123d script in a subprocess; return {stem: path} of STEP/STL outputs."""
        output_dir.mkdir(parents=True, exist_ok=True)
        script_path = output_dir / "_cad_gen.py"
        script_path.write_text(script, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(output_dir),
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise CADError(
                f"build123d script failed (exit {result.returncode}):\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

        outputs: dict[str, Path] = {}
        for path in output_dir.iterdir():
            if path.suffix.lower() in {".step", ".stp", ".stl"}:
                outputs[path.stem] = path
        return outputs

    # ── Feather board STEP (parametric, used when S4 hasn't run yet) ──────────

    def generate_feather_board_step(self, output_dir: Path) -> Path:
        """Generate a parametric Feather PCB outline as STEP for S5 clearance check.

        Phase 1 simplification: we construct the board from known Feather dimensions
        rather than exporting from a real KiCad PCB (that requires S4 to complete first).
        """
        from mandrel.standards.form_factors.feather import (
            BOARD_LENGTH_MM,
            BOARD_THICKNESS_MM,
            BOARD_WIDTH_MM,
            MOUNT_HOLE_DRILL_MM,
            USB_C_HEIGHT_MM,
            USB_C_OVERHANG_MM,
            USB_C_WIDTH_MM,
            mount_holes_centered,
        )

        holes = mount_holes_centered()
        hole_r = MOUNT_HOLE_DRILL_MM / 2

        script = f"""\
from build123d import *
# export_step is top-level in build123d >= 0.9

board_l = {BOARD_LENGTH_MM}
board_w = {BOARD_WIDTH_MM}
board_h = {BOARD_THICKNESS_MM}
hole_r  = {hole_r}
usb_w   = {USB_C_WIDTH_MM}
usb_h   = {USB_C_HEIGHT_MM}
usb_oh  = {USB_C_OVERHANG_MM}
holes   = {holes!r}

with BuildPart() as bp:
    Box(board_l, board_w, board_h)
    with Locations(*[Location((x, y)) for x, y in holes]):
        Hole(hole_r)
    # USB-C connector stub representing its overhang beyond the board edge
    with Locations(Location((-board_l / 2 - usb_oh / 2, 0, board_h / 2 + usb_h / 2))):
        Box(usb_oh + 1, usb_w, usb_h, mode=Mode.ADD)

export_step(bp.part, "feather_board.step")
print("OK: feather_board.step")
"""
        outputs = self.run_script(script, output_dir)
        path = outputs.get("feather_board", output_dir / "feather_board.step")
        if not path.exists():
            raise CADError("build123d did not produce feather_board.step")
        return path

    # ── Feather box enclosure STEP (parametric) ───────────────────────────────

    def generate_feather_enclosure_step(
        self,
        output_dir: Path,
        wall_mm: float = 2.0,
        clearance_mm: float = 0.5,
        lid_clearance_mm: float = 8.0,
    ) -> Path:
        """Generate a simple box enclosure for a Feather board.

        The enclosure is a hollow box with:
        - 2 mm walls on all sides and bottom
        - 0.5 mm clearance between board edge and inner wall
        - 8 mm of vertical clearance above the PCB surface for components
        - USB-C cutout at one short end
        """
        from mandrel.standards.form_factors.feather import (
            BOARD_LENGTH_MM,
            BOARD_THICKNESS_MM,
            BOARD_WIDTH_MM,
            USB_C_HEIGHT_MM,
            USB_C_WIDTH_MM,
        )

        inner_l = BOARD_LENGTH_MM + 2 * clearance_mm
        inner_w = BOARD_WIDTH_MM  + 2 * clearance_mm
        inner_h = BOARD_THICKNESS_MM + lid_clearance_mm
        outer_l = inner_l + 2 * wall_mm
        outer_w = inner_w + 2 * wall_mm
        outer_h = inner_h + wall_mm          # solid floor, open top

        usb_cut_w = USB_C_WIDTH_MM + 1.0     # 0.5 mm clearance each side
        usb_cut_h = USB_C_HEIGHT_MM + 1.0
        # Z centre of USB cutout: floor + board_h/2 + half connector height
        usb_z_from_bottom = wall_mm + BOARD_THICKNESS_MM / 2 + USB_C_HEIGHT_MM / 2
        usb_z_centre = usb_z_from_bottom - outer_h / 2   # convert to body-centred coords

        script = f"""\
from build123d import *
# export_step is top-level in build123d >= 0.9

outer_l = {outer_l}
outer_w = {outer_w}
outer_h = {outer_h}
inner_l = {inner_l}
inner_w = {inner_w}
inner_h = {inner_h}
wall    = {wall_mm}
usb_w   = {usb_cut_w}
usb_h   = {usb_cut_h}
usb_z   = {usb_z_centre}

with BuildPart() as enc:
    # Outer shell
    Box(outer_l, outer_w, outer_h)
    # Hollow cavity (open at top — no lid modelled in Phase 1)
    with Locations(Location((0, 0, wall / 2))):
        Box(inner_l, inner_w, inner_h, mode=Mode.SUBTRACT)
    # USB-C cutout at the left short wall
    with Locations(Location((-outer_l / 2, 0, usb_z))):
        Box(wall + 2, usb_w, usb_h, mode=Mode.SUBTRACT)

export_step(enc.part, "feather_enclosure.step")
print("OK: feather_enclosure.step")
"""
        outputs = self.run_script(script, output_dir)
        path = outputs.get("feather_enclosure", output_dir / "feather_enclosure.step")
        if not path.exists():
            raise CADError("build123d did not produce feather_enclosure.step")
        return path
