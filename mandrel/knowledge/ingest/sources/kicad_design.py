"""Tier-1 source: measure real placements from a permissively-licensed
.kicad_pcb and emit measurement-backed design observations.

This is how Mandrel learns optimal spacing/proximity from working boards:
parse footprint positions, classify each part, and compute the actual
distances designers used (e.g. decoupling cap -> nearest IC). Each emitted
rule is stamped with the design's source + license.
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path
from typing import Any

from mandrel.knowledge.classify import classify
from mandrel.knowledge.schema import Applicability, DesignRule


def measure_kicad_pcb(
    pcb_path: str | Path, source: str = "", license: str = "unknown"
) -> list[DesignRule]:
    """Measure a board and return measurement-backed DesignRules (advisory)."""
    path = Path(pcb_path)
    src = source or str(path)
    try:
        tree = _parse_sexp(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    parts = _footprints(tree)
    if not parts:
        return []

    rules: list[DesignRule] = []
    ic_classes = {"mcu", "ic", "sensor", "ldo", "regulator"}
    ics = [p for p in parts if p["cls"] in ic_classes]
    decaps = [p for p in parts if p["cls"] == "decoupling_cap"]

    # Measure decoupling-cap -> nearest-IC distances.
    if ics and decaps:
        dists = [
            min(_dist(c, ic) for ic in ics)
            for c in decaps
        ]
        mx, med = round(max(dists), 2), round(statistics.median(dists), 2)
        rules.append(DesignRule(
            id=f"measured-decap-dist-{_slug(path.stem)}",
            category="decoupling",
            severity="advisory",
            statement=(
                f"In reference design '{path.stem}', decoupling capacitors sit "
                f"within {mx} mm of their nearest IC (median {med} mm) — "
                "evidence that bypass caps belong right at the device."
            ),
            constraints={"observed_max_distance_mm": mx, "observed_median_mm": med},
            applicability=Applicability(part_classes=["decoupling_cap"], net_classes=["power"]),
            rationale="Measured from a real, working board.",
            tags=["measured", "tier1"],
            source=src,
            license=license,
            confidence=0.5,
        ))

    return rules


# ── minimal self-contained S-expression parsing ────────────────────────────


def _footprints(tree: list) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for node in _find_sexp_nodes(tree, "footprint"):
        ref = None
        for child in _find_sexp_nodes(node, "property"):
            if len(child) > 2 and child[1] == "Reference":
                ref = child[2]
                break
        at = next((c for c in node if isinstance(c, list) and c and c[0] == "at"), None)
        lib = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        if ref is None or at is None or len(at) < 3:
            continue
        try:
            x, y = float(at[1]), float(at[2])
        except ValueError:
            continue
        value = ""
        for child in _find_sexp_nodes(node, "property"):
            if len(child) > 2 and child[1] == "Value":
                value = child[2]
                break
        cls = classify({"ref": ref, "value": value, "footprint": lib})
        parts.append({"ref": ref, "x": x, "y": y, "cls": cls})
    return parts


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "design"


def _parse_sexp(text: str) -> list:
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    pos = 0

    def parse() -> Any:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        if tok == "(":
            node = []
            while pos < len(tokens) and tokens[pos] != ")":
                node.append(parse())
            if pos >= len(tokens):
                raise ValueError("unbalanced")
            pos += 1
            return node
        if tok == ")":
            raise ValueError("unexpected )")
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            return tok[1:-1].replace('\\"', '"')
        return tok

    result = parse()
    return result if isinstance(result, list) else [result]


def _find_sexp_nodes(tree: list, tag: str) -> list[list]:
    found: list[list] = []
    if tree and tree[0] == tag:
        found.append(tree)
    for child in tree:
        if isinstance(child, list):
            found.extend(_find_sexp_nodes(child, tag))
    return found
