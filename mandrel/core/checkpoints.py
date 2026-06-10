"""Human checkpoint implementations.

AutoApproveCheckpoint: for tests and automated runs where no human is present.
CliCheckpoint: blocks on stdin — for Phase 0/1 interactive use.
"""

from __future__ import annotations

from pathlib import Path

from .state import DesignState
from .workflow import Decision


class AutoApproveCheckpoint:
    """Always approves. Use in tests and non-interactive pipelines."""

    def request(self, state: DesignState, artifacts: list[Path]) -> Decision:
        return Decision.APPROVE


class CliCheckpoint:
    """Blocks until the user types approve / edit / reject on stdin."""

    def __init__(self, label: str = "") -> None:
        self.label = label

    def request(self, state: DesignState, artifacts: list[Path]) -> Decision:
        print(f"\n{'='*60}")
        print(f"HUMAN CHECKPOINT: {self.label or 'review required'}")
        print(f"Project: {state.project_id}")
        if artifacts:
            print("Artifacts:")
            for a in artifacts:
                print(f"  {a}")
        print("='*60")
        while True:
            choice = input("Decision [approve/edit/reject]: ").strip().lower()
            try:
                return Decision(choice)
            except ValueError:
                print(f"  Please enter one of: {', '.join(d.value for d in Decision)}")
