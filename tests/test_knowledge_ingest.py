"""Tests for the knowledge ingestion pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mandrel.knowledge.ingest import IngestPipeline, RuleStore
from mandrel.knowledge.ingest.base import RawDocument, is_license_excluded
from mandrel.knowledge.ingest.extractor import RuleExtractor
from mandrel.knowledge.ingest.sources.text import from_text_file
from mandrel.knowledge.ingest.sources.web import html_to_text
from mandrel.knowledge.schema import DesignRule

_LLM_RULES = json.dumps([
    {
        "id": "vbus-trace-width",
        "category": "trace",
        "statement": "Make VBUS power traces at least 0.4 mm wide for USB current.",
        "severity": "should",
        "constraints": {"min_width_mm": 0.4},
        "applicability": {"net_classes": ["power"]},
        "rationale": "Carries up to 3 A.",
    }
])


def _mock_llm(payload: str = _LLM_RULES):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=payload)
    return llm


def test_license_exclusion():
    assert is_license_excluded("CC-BY-SA-4.0")
    assert is_license_excluded("CERN-OHL-S")
    assert is_license_excluded("GPL-3.0")
    assert not is_license_excluded("MIT")
    assert not is_license_excluded("Apache-2.0")


def test_html_to_text():
    title, text = html_to_text(
        "<html><head><title>Design Guide</title><style>x{}</style></head>"
        "<body><script>bad()</script><p>Keep caps near pins.</p></body></html>"
    )
    assert title == "Design Guide"
    assert "Keep caps near pins." in text
    assert "bad()" not in text and "x{}" not in text


def test_text_source(tmp_path: Path):
    f = tmp_path / "guide.md"
    f.write_text("Decoupling caps go close to the pin.")
    doc = from_text_file(f, license="authored", tier=0)
    assert doc.tier == 0 and doc.license == "authored"
    assert "Decoupling" in doc.content


@pytest.mark.asyncio
async def test_extractor_stamps_provenance():
    ex = RuleExtractor(_mock_llm())
    doc = RawDocument(content="some design text", source="http://ex.com/guide",
                      license="MIT", tier=2)
    rules = await ex.extract(doc)
    assert len(rules) == 1
    r = rules[0]
    assert r.source == "http://ex.com/guide"
    assert r.license == "MIT"           # license stamped from source, not LLM
    assert r.category == "trace"
    assert r.constraints["min_width_mm"] == 0.4


@pytest.mark.asyncio
async def test_extractor_handles_garbage():
    ex = RuleExtractor(_mock_llm("the model rambled with no json"))
    rules = await ex.extract(RawDocument(content="x", source="s"))
    assert rules == []


def test_store_dedup(tmp_path: Path):
    store = RuleStore(tmp_path / "pack.yaml")
    r1 = DesignRule(id="a", category="spacing", statement="Keep parts 0.5 mm apart.")
    r2 = DesignRule(id="b", category="spacing", statement="Keep the parts 0.5 mm apart.")  # ~dup
    r3 = DesignRule(id="c", category="trace", statement="Widen power traces.")
    added, deduped = store.add_many([r1, r2, r3])
    assert added == 2 and deduped == 1
    store.save()
    assert (tmp_path / "pack.yaml").exists()
    # reload round-trips
    store2 = RuleStore(tmp_path / "pack.yaml")
    assert len(store2) == 2


@pytest.mark.asyncio
async def test_pipeline_skips_excluded_license(tmp_path: Path):
    pipe = IngestPipeline(_mock_llm(), tmp_path / "out.yaml")
    docs = [
        RawDocument(content="x", source="sa", license="CC-BY-SA-4.0"),
        RawDocument(content="y", source="ok", license="MIT"),
    ]
    stats = await pipe.ingest_documents(docs)
    assert stats.skipped_license == 1
    assert stats.rules_added == 1  # only the MIT doc produced a rule


def test_measure_kicad_pcb(tmp_path: Path):
    from mandrel.knowledge.ingest.sources.kicad_design import measure_kicad_pcb
    # minimal board: an MCU and a decoupling cap 0.8mm apart
    pcb = tmp_path / "ref.kicad_pcb"
    pcb.write_text(
        '(kicad_pcb\n'
        ' (footprint "Package_QFN:QFN-56" (at 20 20)\n'
        '   (property "Reference" "U1") (property "Value" "RP2040"))\n'
        ' (footprint "Capacitor_SMD:C_0402" (at 20.8 20)\n'
        '   (property "Reference" "C1") (property "Value" "100nF"))\n'
        ')\n'
    )
    rules = measure_kicad_pcb(pcb, license="MIT")
    assert len(rules) == 1
    assert rules[0].category == "decoupling"
    assert rules[0].license == "MIT"
    assert rules[0].constraints["observed_max_distance_mm"] == 0.8
