"""Knowledge providers — the free/paid seam.

NullKnowledgeProvider: ships with the OSS core; returns no rules, so the
pipeline runs identically with no knowledge base.

RulePackProvider: loads authored/ingested YAML rule packs (the paid artifact)
and answers context queries by structured filtering. Semantic (pgvector)
retrieval is a planned enhancement layered on top of this same interface.

get_provider() selects based on config: knowledge_enabled + knowledge_packs_dir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from .schema import DesignRule, RuleQuery


@runtime_checkable
class KnowledgeProvider(Protocol):
    def query(self, q: RuleQuery) -> list[DesignRule]:
        """Return design rules relevant to the query context, best first."""
        ...

    def is_empty(self) -> bool:
        ...


class NullKnowledgeProvider:
    """OSS default — no knowledge base."""

    def query(self, q: RuleQuery) -> list[DesignRule]:
        return []

    def is_empty(self) -> bool:
        return True


class RulePackProvider:
    """Loads YAML rule packs from a directory and filters by query context."""

    def __init__(self, packs_dir: Path | str) -> None:
        self._dir = Path(packs_dir)
        self._rules: list[DesignRule] = []
        self._load()

    def _load(self) -> None:
        if not self._dir.is_dir():
            return
        for path in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            for raw in doc.get("rules", []):
                try:
                    self._rules.append(DesignRule.model_validate(raw))
                except Exception:
                    # A malformed rule must never break the pipeline.
                    continue

    def query(self, q: RuleQuery) -> list[DesignRule]:
        hits = [r for r in self._rules if r.matches(q)]
        # Order: severity (must > should > advisory), then confidence.
        sev_rank = {"must": 0, "should": 1, "advisory": 2}
        hits.sort(key=lambda r: (sev_rank.get(r.severity, 3), -r.confidence))
        return hits[: q.limit]

    def is_empty(self) -> bool:
        return not self._rules

    def __len__(self) -> int:
        return len(self._rules)


def get_provider() -> KnowledgeProvider:
    """Select a provider from config (paid RulePack when enabled, else Null)."""
    from mandrel.config import settings

    if not getattr(settings, "knowledge_enabled", False):
        return NullKnowledgeProvider()
    packs_dir = getattr(settings, "knowledge_packs_dir", "")
    if not packs_dir:
        # Default to the bundled starter pack shipped in this package.
        packs_dir = str(Path(__file__).parent / "rules")
    provider = RulePackProvider(packs_dir)
    return provider if not provider.is_empty() else NullKnowledgeProvider()


def format_rules_for_prompt(rules: list[DesignRule]) -> str:
    """Render rules as a compact, prompt-injectable bullet list grouped by category."""
    if not rules:
        return ""
    by_cat: dict[str, list[DesignRule]] = {}
    for r in rules:
        by_cat.setdefault(r.category, []).append(r)
    lines: list[str] = []
    for cat in sorted(by_cat):
        lines.append(f"[{cat}]")
        for r in by_cat[cat]:
            mark = {"must": "MUST", "should": "SHOULD", "advisory": "may"}.get(r.severity, "")
            lines.append(f"- ({mark}) {r.statement}")
    return "\n".join(lines)
