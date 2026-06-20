"""Tests for the explainable KB placement evaluator."""

from __future__ import annotations

from mandrel.knowledge.evaluate import evaluate_placement
from mandrel.knowledge.schema import Applicability, DesignRule

_DECAP_RULE = DesignRule(
    id="decap-proximity-power-pin", category="decoupling", severity="must",
    statement="Decoupling cap within 1 mm of the IC.",
    constraints={"max_distance_mm": 1.0},
    applicability=Applicability(part_classes=["decoupling_cap"]),
    rationale="Loop inductance.",
)
_SPACING_RULE = DesignRule(
    id="spacing-gap", category="spacing", severity="must",
    statement="Keep 0.5 mm courtyard gap.",
    constraints={"min_courtyard_gap_mm": 0.5},
)

_COMPONENTS = [
    {"ref": "U1", "value": "RP2040", "footprint": "Package_QFN:QFN-56", "size_mm": [8.0, 8.0]},
    {"ref": "C1", "value": "100nF", "footprint": "Capacitor_SMD:C_0402", "size_mm": [1.0, 0.5]},
]


def test_decap_proximity_pass():
    placements = [
        {"ref": "U1", "x_mm": 20.0, "y_mm": 20.0},
        {"ref": "C1", "x_mm": 20.8, "y_mm": 20.0},  # 0.8 mm away → within 1 mm
    ]
    evals = evaluate_placement(_COMPONENTS, placements, [_DECAP_RULE])
    e = next(x for x in evals if x.rule_id == "decap-proximity-power-pin")
    assert e.status == "pass"
    assert e.findings[0].measured_mm == 0.8
    assert "C1 is 0.8 mm from U1" in e.findings[0].detail


def test_decap_proximity_fail_explains_why():
    placements = [
        {"ref": "U1", "x_mm": 20.0, "y_mm": 20.0},
        {"ref": "C1", "x_mm": 25.0, "y_mm": 20.0},  # 5 mm away → fails 1 mm
    ]
    evals = evaluate_placement(_COMPONENTS, placements, [_DECAP_RULE])
    e = next(x for x in evals if x.rule_id == "decap-proximity-power-pin")
    assert e.status == "fail"
    assert e.findings[0].measured_mm == 5.0
    assert e.findings[0].ok is False
    assert e.severity == "must"          # so the UI can flag it prominently


def test_spacing_detects_overlap():
    placements = [
        {"ref": "U1", "x_mm": 20.0, "y_mm": 20.0},
        {"ref": "C1", "x_mm": 22.0, "y_mm": 20.0},  # centres 2mm, half-extents 4+0.5 → overlap
    ]
    evals = evaluate_placement(_COMPONENTS, placements, [_SPACING_RULE])
    e = next(x for x in evals if x.rule_id == "spacing-gap")
    assert e.status == "fail"
    assert e.findings[0].ok is False


def test_non_numeric_rule_marked_considered():
    rule = DesignRule(id="orient", category="orientation",
                      statement="Align passives.", severity="should")
    evals = evaluate_placement(_COMPONENTS, [{"ref": "C1", "x_mm": 1, "y_mm": 1}], [rule])
    assert evals[0].status == "considered"


def test_failures_sorted_first():
    placements = [
        {"ref": "U1", "x_mm": 20.0, "y_mm": 20.0},
        {"ref": "C1", "x_mm": 30.0, "y_mm": 20.0},  # far → decap fails
    ]
    rules = [
        DesignRule(id="orient", category="orientation", statement="x", severity="should"),
        _DECAP_RULE,
    ]
    evals = evaluate_placement(_COMPONENTS, placements, rules)
    assert evals[0].status == "fail"     # failure floated to the top
