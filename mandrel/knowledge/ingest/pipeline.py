"""Ingestion orchestrator: sources -> extract/measure -> dedup -> store."""

from __future__ import annotations

from pathlib import Path

from mandrel.knowledge.schema import DesignRule
from mandrel.llm.provider import LLMProvider

from .base import IngestStats, RawDocument, is_license_excluded
from .extractor import RuleExtractor
from .sources.kicad_design import measure_kicad_pcb
from .store import RuleStore


class IngestPipeline:
    """Runs documents/designs through extraction and writes a rule pack."""

    def __init__(self, llm: LLMProvider, out_pack: str | Path) -> None:
        self._extractor = RuleExtractor(llm)
        self._store = RuleStore(out_pack)
        self.stats = IngestStats()

    async def ingest_documents(self, docs: list[RawDocument]) -> IngestStats:
        for doc in docs:
            self.stats.documents += 1
            if is_license_excluded(doc.license):
                self.stats.skipped_license += 1
                self.stats.errors.append(f"license-excluded: {doc.source} ({doc.license})")
                continue
            try:
                rules = await self._extractor.extract(doc)
            except Exception as exc:
                self.stats.errors.append(f"extract failed for {doc.source}: {exc}")
                continue
            self._record(rules)
        return self.stats

    def ingest_kicad_designs(
        self, paths: list[str | Path], license: str = "unknown"
    ) -> IngestStats:
        """Tier-1: measurement-backed rules from permissive .kicad_pcb files."""
        for p in paths:
            self.stats.documents += 1
            if is_license_excluded(license):
                self.stats.skipped_license += 1
                continue
            try:
                rules = measure_kicad_pcb(p, license=license)
            except Exception as exc:
                self.stats.errors.append(f"measure failed for {p}: {exc}")
                continue
            self._record(rules)
        return self.stats

    def _record(self, rules: list[DesignRule]) -> None:
        self.stats.rules_extracted += len(rules)
        added, deduped = self._store.add_many(rules)
        self.stats.rules_added += added
        self.stats.rules_deduped += deduped

    def save(self) -> None:
        self._store.save()
