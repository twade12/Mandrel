"""Mandrel design-knowledge subsystem.

A structured, typed knowledge base of PCB/schematic design rules that both the
LLM (via prompt injection) and deterministic verifiers can consult. Rules are
facts with provenance + license tracking.

Free/paid seam: the OSS core ships the schema, the provider protocol, and a
NullKnowledgeProvider (returns nothing — the pipeline runs identically without
a KB). The paid build supplies populated rule packs and the RulePackProvider /
ingestion tooling. See provider.py.
"""

from .provider import (
    KnowledgeProvider,
    NullKnowledgeProvider,
    RulePackProvider,
    get_provider,
)
from .schema import Applicability, DesignRule, RuleQuery

__all__ = [
    "Applicability",
    "DesignRule",
    "RuleQuery",
    "KnowledgeProvider",
    "NullKnowledgeProvider",
    "RulePackProvider",
    "get_provider",
]
