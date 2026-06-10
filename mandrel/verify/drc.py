"""DRC (Design Rules Check) result parser.

Parses the JSON report produced by `kicad-cli pcb drc --format json`
into a VerifierResult.

KiCad DRC JSON structure (8.0):
  {
    "errors": <int>,
    "warnings": <int>,
    "violations": [
      {
        "type": "clearance" | "footprint" | ...,
        "description": "...",
        "severity": "error" | "warning",
        "items": [{"description": ..., "pos": {"x": ..., "y": ...}}, ...]
      }
    ]
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mandrel.core.state import VerifierResult, Violation


class DRCVerifier:
    """Parse kicad-cli DRC JSON output into a VerifierResult."""

    def check(self, report_path: Path, against: Any = None) -> VerifierResult:
        try:
            data: dict = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return VerifierResult(
                passed=False,
                score=0.0,
                violations=[Violation(
                    code="DRC_PARSE_ERROR",
                    message=f"Could not parse DRC report: {exc}",
                    severity="error",
                )],
            )

        errors   = int(data.get("errors", 0))
        items    = data.get("violations", []) or data.get("items", [])

        violations: list[Violation] = []
        for item in items:
            severity = item.get("severity", "error")
            pos_info = ""
            if item.get("items"):
                first = item["items"][0]
                pos = first.get("pos", {})
                if pos:
                    pos_info = f" @ ({pos.get('x', '?')}, {pos.get('y', '?')})"
            violations.append(Violation(
                code=item.get("type", "DRC").upper().replace(" ", "_"),
                message=item.get("description", str(item)) + pos_info,
                severity=severity,
                location=pos_info.strip() or None,
            ))

        passed = errors == 0
        score  = 1.0 if passed else max(0.0, 1.0 - errors * 0.1)
        return VerifierResult(passed=passed, score=score, violations=violations)
