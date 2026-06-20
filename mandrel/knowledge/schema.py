"""Typed schema for design-rule knowledge.

A DesignRule is a single, provenance-tracked best-practice fact. Rules are
*facts* (largely uncopyrightable) — the value is in the structured, queryable,
checkable form, not in any source's expression. Every rule carries its source
and license so the knowledge base stays auditable for a commercial product.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Categories are intentionally OPEN strings so the knowledge base can grow via
# authoring or ingestion without a schema change every time a new domain area is
# added (e.g. future FreeCAD/mechanical: "enclosure", "fit", "mechanical").
# KNOWN_CATEGORIES documents the curated taxonomy for the UI and the extractor;
# it is reference, not enforcement.
Category = str

KNOWN_CATEGORIES: tuple[str, ...] = (
    # electrical / layout
    "decoupling", "power_integrity", "grounding", "ground_plane", "signal_integrity",
    "high_speed", "high_speed_interfaces", "rf", "rf_antenna", "antenna",
    "oscillator", "mixed_signal", "trace", "routing", "vias", "stackup", "emc",
    "esd_emc", "thermal", "power",
    # placement / mechanical / manufacturing
    "placement", "spacing", "orientation", "connector", "connectors_mechanical",
    "dfm", "dfa", "silkscreen", "test_debug", "safety_hv",
    # reserved for FreeCAD / enclosure work
    "enclosure", "fit", "mechanical",
)

Severity = Literal["must", "should", "advisory"]

# Coarse functional classes a component can belong to (see knowledge.classify).
PartClass = Literal[
    "mcu", "ldo", "regulator", "sensor", "connector", "usb", "crystal",
    "oscillator", "decoupling_cap", "bulk_cap", "resistor", "pullup",
    "led", "diode", "inductor", "antenna", "ic", "unknown",
]


class Applicability(BaseModel):
    """Conditions under which a rule applies. Empty list = applies to all."""

    part_classes: list[str] = Field(default_factory=list)
    net_classes: list[str] = Field(default_factory=list)   # power, ground, rf, clock, high_speed
    form_factors: list[str] = Field(default_factory=list)   # feather, hat, ...; empty = any
    freq_min_hz: float | None = None
    freq_max_hz: float | None = None


class DesignRule(BaseModel):
    """A single design best-practice, structured for query + (where numeric) checking."""

    id: str
    category: Category
    # natural-language rule, injected into prompts
    statement: str
    severity: Severity = "should"
    # numeric/structured constraints, e.g. {"max_distance_mm": 1.0}
    constraints: dict[str, Any] = Field(default_factory=dict)
    applicability: Applicability = Field(default_factory=Applicability)
    rationale: str = ""
    tags: list[str] = Field(default_factory=list)

    # Provenance / licensing — mandatory discipline for the commercial KB.
    source: str = "authored"             # URL, doc id, or "authored"
    license: str = "Apache-2.0"          # license of the rule's expression here
    confidence: float = 0.8              # 0..1 authority/trust

    def matches(self, query: RuleQuery) -> bool:
        """True if this rule is applicable to the given query context."""
        if query.categories and self.category not in query.categories:
            return False
        ap = self.applicability
        if ap.form_factors and query.form_factor and query.form_factor not in ap.form_factors:
            return False
        if ap.part_classes and query.part_classes:
            if not (set(ap.part_classes) & set(query.part_classes)):
                return False
        if ap.net_classes and query.net_classes:
            if not (set(ap.net_classes) & set(query.net_classes)):
                return False
        return True


class RuleQuery(BaseModel):
    """Context used to retrieve relevant rules for a pipeline stage."""

    stage: str                                   # s2_architecture | s3_schematic | s4_layout
    categories: list[Category] = Field(default_factory=list)
    part_classes: list[str] = Field(default_factory=list)
    net_classes: list[str] = Field(default_factory=list)
    form_factor: str | None = None
    limit: int = 40
