"""Tests for the design-knowledge subsystem."""

from __future__ import annotations

from mandrel.knowledge import NullKnowledgeProvider, RulePackProvider, RuleQuery, get_provider
from mandrel.knowledge.classify import classify, classify_all
from mandrel.knowledge.provider import format_rules_for_prompt
from mandrel.knowledge.schema import Applicability, DesignRule


def test_null_provider_returns_nothing():
    p = NullKnowledgeProvider()
    assert p.is_empty()
    assert p.query(RuleQuery(stage="s4_layout")) == []


def test_bundled_packs_load():
    p = get_provider()
    assert isinstance(p, RulePackProvider)
    assert not p.is_empty()
    assert len(p) >= 10


def test_classifier():
    assert classify({"ref": "U1", "value": "RP2040", "footprint": "QFN-56"}) == "mcu"
    assert classify({"ref": "U2", "value": "MIC5219-3.3", "footprint": "SOT-23-5"}) == "ldo"
    assert classify({"ref": "U3", "value": "SHT30", "footprint": "DFN-8"}) == "sensor"
    assert classify({"ref": "C1", "value": "100nF", "footprint": "C_0402"}) == "decoupling_cap"
    assert classify({"ref": "C2", "value": "10uF", "footprint": "C_0805"}) == "bulk_cap"
    assert classify({"ref": "R1", "value": "4.7k", "footprint": "R_0402"}) == "resistor"
    assert classify({"ref": "J1", "value": "USB_C", "footprint": "USB_C_Receptacle"}) == "usb"
    assert classify({"ref": "Y1", "value": "12MHz", "footprint": "Crystal"}) == "crystal"


def test_query_filters_by_part_class():
    p = get_provider()
    # A board with no antenna/crystal must not surface RF/oscillator rules.
    rules = p.query(RuleQuery(
        stage="s4_layout",
        categories=["rf", "oscillator", "decoupling"],
        part_classes=["mcu", "decoupling_cap", "usb"],
        form_factor="feather",
    ))
    cats = {r.category for r in rules}
    assert "decoupling" in cats
    assert "rf" not in cats
    assert "oscillator" not in cats


def test_query_surfaces_rf_when_antenna_present():
    p = get_provider()
    rules = p.query(RuleQuery(
        stage="s4_layout", categories=["rf"], part_classes=["antenna"],
    ))
    assert any(r.category == "rf" for r in rules)


def test_severity_ordering():
    p = get_provider()
    rules = p.query(RuleQuery(stage="s4_layout", part_classes=["decoupling_cap", "mcu"]))
    sev = [r.severity for r in rules]
    # 'must' rules come before 'should'/'advisory'
    if "must" in sev and "advisory" in sev:
        assert sev.index("must") < sev.index("advisory")


def test_decoupling_proximity_rule_is_must():
    p = get_provider()
    rules = p.query(RuleQuery(stage="s4_layout", categories=["decoupling"],
                              part_classes=["decoupling_cap", "mcu"]))
    prox = next((r for r in rules if r.id == "decap-proximity-power-pin"), None)
    assert prox is not None
    assert prox.severity == "must"
    assert prox.constraints.get("max_distance_mm") == 1.0


def test_matches_form_factor_gate():
    rule = DesignRule(
        id="x", category="spacing", statement="s",
        applicability=Applicability(form_factors=["hat"]),
    )
    assert not rule.matches(RuleQuery(stage="s4_layout", form_factor="feather"))
    assert rule.matches(RuleQuery(stage="s4_layout", form_factor="hat"))


def test_format_groups_by_category():
    rules = [
        DesignRule(id="a", category="spacing", statement="keep apart", severity="must"),
        DesignRule(id="b", category="orientation", statement="align", severity="should"),
    ]
    text = format_rules_for_prompt(rules)
    assert "[spacing]" in text and "[orientation]" in text
    assert "MUST" in text
