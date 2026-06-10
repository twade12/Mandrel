"""Pipeline runner and protocol definitions for Stage and Checkpoint.

The PipelineRunner is a thin async sequential runner shaped so it can be
backed by Temporal later without touching Stage code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .state import DesignState, StageRun, VerifierResult

# ── Context ───────────────────────────────────────────────────────────────────


@dataclass
class Context:
    """Runtime context passed to every stage.run() call."""

    project_dir: Path
    config: Any = None  # mandrel.config.Settings — injected at runtime


# ── StageResult ───────────────────────────────────────────────────────────────


@dataclass
class StageResult:
    state: DesignState
    artifacts: list[Path] = field(default_factory=list)
    verifier_result: VerifierResult | None = None


# ── Protocols ─────────────────────────────────────────────────────────────────


@runtime_checkable
class Stage(Protocol):
    name: str

    def run(self, state: DesignState, ctx: Context) -> StageResult:
        ...


class Decision(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


@runtime_checkable
class Checkpoint(Protocol):
    def request(self, state: DesignState, artifacts: list[Path]) -> Decision:
        ...


# ── Pipeline runner ───────────────────────────────────────────────────────────


class PipelineRunner:
    """Sequential async pipeline runner.

    Runs each stage in order, records history, and surfaces verifier failures.
    Interface is stable for a future Temporal-backed implementation:
    callers interact only via run(state, ctx) → DesignState.
    """

    def __init__(
        self,
        stages: list[Stage],
        checkpoints: dict[str, Checkpoint] | None = None,
        max_repair_retries: int = 3,
    ) -> None:
        self.stages = stages
        self.checkpoints: dict[str, Checkpoint] = checkpoints or {}
        self.max_repair_retries = max_repair_retries

    async def run(self, state: DesignState, ctx: Context) -> DesignState:
        for stage in self.stages:
            state = await self._run_stage(stage, state, ctx)
        return state

    async def _run_stage(self, stage: Stage, state: DesignState, ctx: Context) -> DesignState:
        run = StageRun(stage_name=stage.name, started_at=datetime.now(UTC))

        try:
            result: StageResult = await asyncio.to_thread(stage.run, state, ctx)
            run.success = True
            run.completed_at = datetime.now(UTC)
            run.verifier_result = result.verifier_result
            run.artifacts = [str(p) for p in result.artifacts]
            state = result.state
        except Exception as exc:
            run.success = False
            run.completed_at = datetime.now(UTC)
            run.error = str(exc)
            raise

        finally:
            state = state.model_copy(
                update={"history": [*state.history, run], "updated_at": datetime.now(UTC)}
            )

        # Fire checkpoint if one is registered for this stage
        if stage.name in self.checkpoints:
            decision = self.checkpoints[stage.name].request(state, [Path(a) for a in run.artifacts])
            if decision == Decision.REJECT:
                raise RuntimeError(f"Stage '{stage.name}' rejected at human checkpoint.")

        return state
