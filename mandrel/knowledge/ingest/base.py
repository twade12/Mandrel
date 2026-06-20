"""Core ingestion types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawDocument:
    """A unit of source content awaiting rule extraction.

    Provenance and license travel with the content from the moment it enters
    the pipeline, so every emitted rule can be attributed and audited.
    """

    content: str
    source: str                     # URL, file path, or design id
    license: str = "unknown"        # license of the SOURCE material
    title: str = ""
    kind: str = "text"              # text | web | kicad_design
    tier: int = 2                   # 0 authored, 1 permissive design, 2 web/app-note
    meta: dict = field(default_factory=dict)


# Licenses that must NOT feed the closed knowledge base (share-alike / viral).
EXCLUDED_LICENSES = {
    "cc-by-sa", "cc-by-sa-4.0", "cc-by-sa-3.0",
    "cern-ohl-s", "cern-ohl-s-2.0",
    "gpl", "gpl-3.0", "gpl-2.0", "agpl", "agpl-3.0",
}


def is_license_excluded(license_str: str) -> bool:
    """True if the source license is share-alike/viral and must be excluded
    from the closed KB (moderate sourcing posture)."""
    return (license_str or "").strip().lower() in EXCLUDED_LICENSES


@dataclass
class IngestStats:
    """Summary of one ingestion run."""

    documents: int = 0
    skipped_license: int = 0
    rules_extracted: int = 0
    rules_added: int = 0
    rules_deduped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.documents} docs · {self.rules_extracted} extracted · "
            f"{self.rules_added} added · {self.rules_deduped} dup · "
            f"{self.skipped_license} license-skipped · {len(self.errors)} errors"
        )
