"""No-op pipeline stages used in Phase 0 tests.

Each NoopStage passes through the DesignState unchanged and records a clean
StageRun in history, proving the pipeline infrastructure works end-to-end
before any real stage logic is wired in.
"""

from __future__ import annotations

from mandrel.core.state import DesignState, VerifierResult
from mandrel.core.workflow import Context, StageResult


class NoopStage:
    """A stage that does nothing and always passes verification."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
        return StageResult(
            state=state,
            artifacts=[],
            verifier_result=VerifierResult(passed=True, score=1.0),
        )
