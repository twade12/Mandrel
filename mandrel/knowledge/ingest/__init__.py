"""Knowledge ingestion pipeline (paid tier).

Turns external content — curated docs (Tier 0), permissive reference designs
(Tier 1), and app-notes/design-guides (Tier 2) — into structured, provenance-
tracked DesignRules and writes them into the rule packs the RulePackProvider
serves.

Moderate sourcing posture (per product decision): store distilled facts with
source + license, never verbatim copyrighted text, exclude share-alike design
files from the closed knowledge base.

Flow:  Source -> RawDocument -> Extractor (LLM) / Measurer -> dedup -> RuleStore
"""

from .base import IngestStats, RawDocument
from .extractor import RuleExtractor
from .pipeline import IngestPipeline
from .store import RuleStore

__all__ = [
    "RawDocument",
    "IngestStats",
    "RuleExtractor",
    "RuleStore",
    "IngestPipeline",
]
