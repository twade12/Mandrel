"""Explainable, KB-driven evaluation of a PCB placement.

Given the placed components and the applicable design rules, this measures the
layout against each rule's numeric constraints and produces a structured
rationale: which rules applied, what was measured per component, and whether it
passed. This is what lets the UI answer "why was it laid out this way?".

Rules without a checkable numeric constraint are surfaced as "considered" so
the user still sees the full set of best-practices that guided placement.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from .classify import classify
from .schema import DesignRule

_IC_CLASSES = {"mcu", "ic", "sensor", "ldo", "regulator"}


class RuleFinding(BaseModel):
    refs: list[str] = Field(default_factory=list)
    detail: str
    measured_mm: float | None = None
    limit_mm: float | None = None
    ok: bool = True


class RuleEvaluation(BaseModel):
    rule_id: str
    category: str
    statement: str
    severity: str            # must | should | advisory
    rationale: str = ""
    status: str              # pass | fail | considered
    findings: list[RuleFinding] = Field(default_factory=list)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def evaluate_placement(
    components: list[dict],
    placements: list[dict],
    rules: list[DesignRule],
) -> list[RuleEvaluation]:
    """Return a per-rule explainable evaluation of the placement.

    components: [{ref, value, footprint, size_mm?}]
    placements: [{ref, x_mm, y_mm, rotation_deg}]
    """
    pos = {
        p["ref"]: (float(p.get("x_mm", 0.0)), float(p.get("y_mm", 0.0)))
        for p in placements if "ref" in p
    }
    cls = {c["ref"]: classify(c) for c in components if "ref" in c}
    size = {c["ref"]: c.get("size_mm") for c in components if "ref" in c}

    ic_refs = [r for r, k in cls.items() if k in _IC_CLASSES and r in pos]
    cap_refs = [r for r, k in cls.items() if k == "decoupling_cap" and r in pos]

    evals: list[RuleEvaluation] = []
    for rule in rules:
        ev = _evaluate_rule(rule, pos, cls, size, ic_refs, cap_refs)
        if ev is not None:
            evals.append(ev)
    # Failures first, then by severity.
    sev = {"must": 0, "should": 1, "advisory": 2}
    evals.sort(key=lambda e: (e.status != "fail", sev.get(e.severity, 3)))
    return evals


def _evaluate_rule(rule, pos, cls, size, ic_refs, cap_refs) -> RuleEvaluation | None:
    c = rule.constraints or {}

    # Decoupling-cap proximity to nearest IC.
    if rule.category == "decoupling" and "max_distance_mm" in c and cap_refs and ic_refs:
        limit = float(c["max_distance_mm"])
        findings: list[RuleFinding] = []
        for cap in cap_refs:
            nearest = min(ic_refs, key=lambda ic: _dist(pos[cap], pos[ic]))
            d = round(_dist(pos[cap], pos[nearest]), 2)
            findings.append(RuleFinding(
                refs=[cap, nearest], measured_mm=d, limit_mm=limit, ok=d <= limit,
                detail=f"{cap} is {d} mm from {nearest} (limit {limit} mm)",
            ))
        status = "pass" if all(f.ok for f in findings) else "fail"
        return _mk(rule, status, findings)

    # Minimum courtyard gap between component pairs.
    if rule.category == "spacing" and "min_courtyard_gap_mm" in c:
        gap_min = float(c["min_courtyard_gap_mm"])
        refs = [r for r in pos if size.get(r)]
        worst: list[RuleFinding] = []
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a, b = refs[i], refs[j]
                sa, sb = size[a], size[b]
                # centre distance minus half-extents along the dominant axis
                dx = abs(pos[a][0] - pos[b][0]) - (sa[0] + sb[0]) / 2
                dy = abs(pos[a][1] - pos[b][1]) - (sa[1] + sb[1]) / 2
                gap = round(max(dx, dy), 2)
                if gap < gap_min:
                    worst.append(RuleFinding(
                        refs=[a, b], measured_mm=gap, limit_mm=gap_min, ok=False,
                        detail=f"{a}/{b} gap {gap} mm (< {gap_min} mm)",
                    ))
        if worst:
            return _mk(rule, "fail", worst[:8])
        return _mk(rule, "pass", [RuleFinding(
            detail=f"All component pairs keep >= {gap_min} mm courtyard gap.", ok=True,
        )])

    # Non-numeric rules: surface as considered (guided the LLM placement).
    return _mk(rule, "considered", [])


def _mk(rule, status: str, findings: list[RuleFinding]) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule.id, category=rule.category, statement=rule.statement,
        severity=rule.severity, rationale=rule.rationale, status=status,
        findings=findings,
    )
