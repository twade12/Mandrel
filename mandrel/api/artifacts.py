"""On-demand artifact rendering for the UI render tabs.

Generates SVG (PCB / schematic) and GLB (board / enclosure 3D) from the files
a run leaves in its project workspace. Results are cached next to the source
and regenerated only when the source is newer.

GPL boundary preserved: kicad-cli runs out-of-process (subprocess). build123d
(Apache-2.0) runs in-process and only handles the enclosure STEP→GLB conversion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mandrel.config import settings

# artifact name → (subdir, source filename glob)
_SOURCES = {
    "pcb.svg": ("s4_layout", "board.kicad_pcb"),
    "board.glb": ("s4_layout", "board.kicad_pcb"),
    "schematic.svg": ("s3_schematic", "*.kicad_sch"),
    "enclosure.glb": ("s5_enclosure", "*.step"),
}

_MEDIA_TYPES = {".svg": "image/svg+xml", ".glb": "model/gltf-binary"}


class ArtifactError(RuntimeError):
    pass


def _source_path(project_dir: Path, name: str) -> Path | None:
    if name not in _SOURCES:
        return None
    subdir, pattern = _SOURCES[name]
    base = project_dir / subdir
    if not base.is_dir():
        return None
    if "*" in pattern:
        hits = sorted(base.glob(pattern))
        return hits[0] if hits else None
    p = base / pattern
    return p if p.exists() else None


def _fresh(out: Path, src: Path) -> bool:
    return out.exists() and out.stat().st_mtime >= src.stat().st_mtime


def media_type(name: str) -> str:
    return _MEDIA_TYPES.get(Path(name).suffix, "application/octet-stream")


def render(project_dir: Path, name: str) -> Path:
    """Return a path to the rendered artifact, generating/caching as needed."""
    src = _source_path(project_dir, name)
    if src is None:
        raise ArtifactError(f"source for {name} not available yet")

    out = project_dir / "_render" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    if _fresh(out, src):
        return out

    if name == "pcb.svg":
        _kicad([
            "pcb", "export", "svg",
            "--output", str(out),
            "--layers", "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen,F.Fab",
            "--page-size-mode", "2",  # crop to board
            "--exclude-drawing-sheet",
            str(src),
        ])
    elif name == "board.glb":
        _kicad(["pcb", "export", "glb", "--output", str(out), str(src)])
    elif name == "schematic.svg":
        _kicad(["sch", "export", "svg", "--output", str(out.parent), str(src)])
        # kicad-cli writes <sheetname>.svg into the dir; normalize to out.
        produced = sorted(out.parent.glob("*.svg"))
        if not produced:
            raise ArtifactError("schematic SVG not produced")
        if produced[0] != out:
            produced[0].replace(out)
    elif name == "enclosure.glb":
        _step_to_glb(src, out)
    else:
        raise ArtifactError(f"unknown artifact {name}")

    if not out.exists():
        raise ArtifactError(f"failed to render {name}")
    return out


def _kicad(args: list[str]) -> None:
    result = subprocess.run(
        [settings.kicad_cli_path, *args],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise ArtifactError(f"kicad-cli {args[0]} {args[1]} failed: {result.stderr[:300]}")


def _step_to_glb(step_path: Path, out: Path) -> None:
    """Convert an enclosure STEP to GLB via build123d (Apache-2.0, in-process)."""
    try:
        from build123d import export_gltf, import_step
    except ImportError as exc:  # pragma: no cover
        raise ArtifactError(f"build123d unavailable: {exc}") from exc
    shape = import_step(str(step_path))
    export_gltf(shape, str(out), binary=True)
