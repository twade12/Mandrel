"""ERC (Electrical Rules Check) result parser.

Parses the JSON report produced by `kicad-cli sch erc --format json`
into a VerifierResult.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mandrel.core.state import VerifierResult, Violation


class ERCVerifier:
    """Parse kicad-cli ERC JSON output into a VerifierResult."""

    def check(self, report_path: Path, against: Any = None) -> VerifierResult:
        """Load and parse an ERC JSON report file."""
        try:
            data: dict = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return VerifierResult(
                passed=False,
                score=0.0,
                violations=[Violation(
                    code="ERC_PARSE_ERROR",
                    message=f"Could not parse ERC report: {exc}",
                    severity="error",
                )],
            )

        errors = int(data.get("errors", 0))
        items  = data.get("items", []) or data.get("violations", [])

        violations: list[Violation] = []
        for item in items:
            severity = "warning" if item.get("type", "error") == "warning" else "error"
            violations.append(Violation(
                code=item.get("type", "ERC"),
                message=item.get("description", str(item)),
                severity=severity,
                location=str(item.get("pos", "")),
            ))

        # Warnings alone don't block the gate.
        passed = errors == 0
        score  = 1.0 if passed else max(0.0, 1.0 - errors * 0.1)

        return VerifierResult(passed=passed, score=score, violations=violations)
