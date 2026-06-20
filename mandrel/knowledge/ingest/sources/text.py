"""Local text / markdown source (Tier 0-2 depending on provenance)."""

from __future__ import annotations

from pathlib import Path

from ..base import RawDocument


def from_text_file(
    path: str | Path, source: str = "", license: str = "authored", tier: int = 0
) -> RawDocument:
    p = Path(path)
    return RawDocument(
        content=p.read_text(encoding="utf-8", errors="replace"),
        source=source or str(p),
        license=license,
        title=p.stem,
        kind="text",
        tier=tier,
    )
