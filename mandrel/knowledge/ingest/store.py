"""Persist extracted rules into a YAML rule pack, with dedup."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from mandrel.knowledge.schema import DesignRule


def _normalize(text: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())


def _similar(a: str, b: str, threshold: float = 0.7) -> bool:
    ta, tb = _normalize(a), _normalize(b)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= threshold


class RuleStore:
    """Append-with-dedup writer for a single YAML rule pack."""

    def __init__(self, pack_path: str | Path) -> None:
        self._path = Path(pack_path)
        self._rules: list[DesignRule] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        doc = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        for raw in doc.get("rules", []):
            try:
                self._rules.append(DesignRule.model_validate(raw))
            except Exception:
                continue

    def _is_duplicate(self, rule: DesignRule) -> bool:
        for existing in self._rules:
            if existing.id == rule.id:
                return True
            if existing.category == rule.category and _similar(existing.statement, rule.statement):
                return True
        return False

    def add(self, rule: DesignRule) -> bool:
        """Add a rule; return False if it was a duplicate."""
        if self._is_duplicate(rule):
            return False
        self._rules.append(rule)
        return True

    def add_many(self, rules: list[DesignRule]) -> tuple[int, int]:
        added = deduped = 0
        for r in rules:
            if self.add(r):
                added += 1
            else:
                deduped += 1
        return added, deduped

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "_generated": "mandrel knowledge ingest",
            "rules": [r.model_dump(exclude_defaults=False) for r in self._rules],
        }
        self._path.write_text(
            yaml.safe_dump(data, sort_keys=False, width=100, allow_unicode=True),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self._rules)
