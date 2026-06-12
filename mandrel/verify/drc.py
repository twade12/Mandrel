"""DRC (Design Rules Check) result parser.

Parses the JSON report produced by `kicad-cli pcb drc --format json`
into a VerifierResult.

KiCad 9 DRC JSON structure (verified against a real 9.0.9 report — there
is NO top-level errors/warnings count):
  {
    "$schema": ..., "kicad_version": ..., "source": ...,
    "violations": [
      {
        "type": "clearance" | "shorting_items" | ...,
        "description": "...",
        "severity": "error" | "warning",
        "items": [{"description": ..., "pos": {"x": ..., "y": ...}}, ...]
      }
    ],
    "unconnected_items": [ ...same shape... ],   # unrouted connections
    "schematic_parity": [ ...same shape... ]
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

        violations: list[Violation] = []

        def add_items(items: list, default_code: str) -> None:
            for item in items:
                severity = item.get("severity", "error")
                pos_info = ""
                if item.get("items"):
                    first = item["items"][0]
                    pos = first.get("pos", {})
                    if pos:
                        pos_info = f" @ ({pos.get('x', '?')}, {pos.get('y', '?')})"
                violations.append(Violation(
                    code=item.get("type", default_code).upper().replace(" ", "_"),
                    message=item.get("description", str(item)) + pos_info,
                    severity=severity,
                    location=pos_info.strip() or None,
                ))

        add_items(data.get("violations", []) or data.get("items", []), "DRC")
        add_items(data.get("unconnected_items", []), "UNCONNECTED")
        add_items(data.get("schematic_parity", []), "PARITY")

        # Count errors from the parsed items; KiCad 9 has no top-level count.
        # Fall back to a legacy top-level "errors" field if one exists.
        errors = sum(1 for v in violations if v.severity == "error")
        errors = max(errors, int(data.get("errors", 0)))

        passed = errors == 0
        score  = 1.0 if passed else max(0.0, 1.0 - errors * 0.1)
        return VerifierResult(passed=passed, score=score, violations=violations)
