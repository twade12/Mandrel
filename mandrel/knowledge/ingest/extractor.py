"""LLM-based rule extraction: RawDocument -> [DesignRule].

The model reads a chunk of design content and emits structured rules. We keep
only the distilled facts (statement + numeric constraints + applicability),
never the source's verbatim text, and stamp each with the document's source +
license for auditability.
"""

from __future__ import annotations

import json
import re

from mandrel.knowledge.schema import DesignRule
from mandrel.llm.provider import LLMProvider, Message

from .base import RawDocument

_CATEGORIES = (
    "decoupling, oscillator, rf, connector, trace, ground_plane, orientation, "
    "spacing, placement, thermal, emc, power"
)

_EXTRACT_PROMPT = """\
You are a PCB design expert building a structured knowledge base. Read the
SOURCE CONTENT below and extract concrete, reusable PCB/schematic design rules
as a JSON array. Extract only durable engineering FACTS — not marketing,
not part-specific trivia, not prose. If the content has no general design
rules, return [].

Each rule object:
{{
  "id": "<short-kebab-id>",
  "category": "<one of: {categories}>",
  "statement": "<imperative rule, one or two sentences, in your own words>",
  "severity": "must | should | advisory",
  "constraints": {{ "<numeric_key_mm_or_value>": <number> }},   // optional, only if quantitative
  "applicability": {{
     "part_classes": [],   // e.g. mcu, ldo, sensor, decoupling_cap, bulk_cap, connector, usb, crystal, antenna
     "net_classes": [],    // e.g. power, ground, clock, rf, high_speed
     "form_factors": []    // usually [] (general)
  }},
  "rationale": "<why, one sentence>",
  "tags": []
}}

RULES FOR YOU:
- Paraphrase into your own words; never copy sentences verbatim.
- Prefer quantitative constraints (distances in mm, widths, clearances) when stated.
- category MUST be one of the listed values.
- Return ONLY the JSON array.

SOURCE TITLE: {title}
SOURCE CONTENT:
{content}
"""


class RuleExtractor:
    def __init__(self, llm: LLMProvider, max_chars: int = 6000) -> None:
        self._llm = llm
        self._max_chars = max_chars

    async def extract(self, doc: RawDocument) -> list[DesignRule]:
        content = doc.content.strip()
        if not content:
            return []
        prompt = _EXTRACT_PROMPT.format(
            categories=_CATEGORIES,
            title=doc.title or doc.source,
            content=content[: self._max_chars],
        )
        raw = await self._llm.complete([Message(role="user", content=prompt)], temperature=0.1)
        items = _parse_json_array(raw)
        rules: list[DesignRule] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Stamp provenance/license from the source document.
            item.setdefault("source", doc.source)
            item["source"] = doc.source
            item["license"] = doc.license
            item.setdefault("confidence", 0.6 if doc.tier >= 2 else 0.75)
            try:
                rules.append(DesignRule.model_validate(item))
            except Exception:
                continue
        return rules


def _parse_json_array(text: str) -> list:
    clean = re.sub(r"```(?:json)?", "", text).strip()
    start = clean.find("[")
    end = clean.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(clean[start : end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
