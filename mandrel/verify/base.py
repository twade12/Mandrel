"""Verifier protocol — deterministic, non-LLM gates.

A verifier inspects an artifact against a spec or standard and returns a
VerifierResult. It must never call an LLM; it is the part of the system
that cannot be deceived by model hallucination.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from mandrel.core.state import VerifierResult


@runtime_checkable
class Verifier(Protocol):
    def check(self, artifact: Path, against: Any) -> VerifierResult:
        """Inspect artifact and return a pass/fail result with violations."""
        ...
