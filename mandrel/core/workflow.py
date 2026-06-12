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


STAGE_LABELS: dict[str, str] = {
    "s1_intent":       "Extract Spec",
    "s2_architecture": "Architecture",
    "s3_schematic":    "Schematic + ERC",
    "s4_layout":       "PCB Layout + DRC",
    "s5_enclosure":    "Enclosure",
    "s6_bom":          "BOM & Sourcing",
}


@dataclass
class Context:
    """Runtime context passed to every stage.run() call."""

    project_dir: Path
    config: Any = None   # mandrel.config.Settings — injected at runtime
    on_event: Any = None  # Optional async callable: async def on_event(event: dict) -> None

    async def progress(self, stage: str, message: str) -> None:
        """Emit a sub-stage progress message so the UI can show what's running."""
        if self.on_event:
            await self.on_event({"type": "stage_progress", "stage": stage, "message": message})

    def stream_reporter(
        self,
        stage: str,
        prefix: str,
        interval_s: float = 2.0,
        tail_chars: int = 1500,
    ) -> Any:
        """Build an on_token callback for LLMProvider.complete() that emits
        throttled stage_progress events carrying a live tail of the output."""
        import time

        buf: list[str] = []
        last_emit = {"t": 0.0}

        async def on_token(delta: str, total_chars: int) -> None:
            buf.append(delta)
            now = time.monotonic()
            if now - last_emit["t"] < interval_s or not self.on_event:
                return
            last_emit["t"] = now
            await self.on_event({
                "type": "stage_progress",
                "stage": stage,
                "message": f"{prefix} — {total_chars:,} chars generated…",
                "detail": "".join(buf)[-tail_chars:],
            })

        return on_token


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

    async def run(self, state: DesignState, ctx: Context) -> StageResult:
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
        label = STAGE_LABELS.get(stage.name, stage.name)
        run = StageRun(stage_name=stage.name, started_at=datetime.now(UTC))

        await _emit(ctx, {"type": "stage_started", "stage": stage.name, "label": label})

        try:
            result: StageResult = await stage.run(state, ctx)
            run.success = True
            run.completed_at = datetime.now(UTC)
            run.verifier_result = result.verifier_result
            run.artifacts = [str(p) for p in result.artifacts]
            state = result.state
        except Exception as exc:
            run.success = False
            run.completed_at = datetime.now(UTC)
            err_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            run.error = err_msg
            await _emit(ctx, {
                "type": "stage_failed", "stage": stage.name, "label": label, "error": err_msg,
            })
            raise

        finally:
            state = state.model_copy(
                update={"history": [*state.history, run], "updated_at": datetime.now(UTC)}
            )

        vr = result.verifier_result
        await _emit(ctx, {
            "type": "stage_completed",
            "stage": stage.name,
            "label": label,
            "passed": vr.passed if vr else True,
            "score": vr.score if vr else 1.0,
            "violations": [v.model_dump() for v in vr.violations] if vr else [],
            "state": state.model_dump(mode="json"),
        })

        # Verification-first gate (spec §0): a stage whose deterministic verifier
        # failed must not let the pipeline advance.
        if vr is not None and not vr.passed:
            errors = "; ".join(
                f"{v.code}: {v.message}" for v in vr.violations if v.severity == "error"
            ) or "verifier failed"
            raise RuntimeError(f"Stage '{label}' failed verification — {errors}")

        # Fire checkpoint if one is registered for this stage
        if stage.name in self.checkpoints:
            cp = self.checkpoints[stage.name]
            cp_label = getattr(cp, "label", "") or label
            await _emit(ctx, {
                "type": "checkpoint_needed",
                "stage": stage.name,
                "label": label,
                "summary": cp_label,
                "state": state.model_dump(mode="json"),
            })
            artifacts = [Path(a) for a in run.artifacts]
            if asyncio.iscoroutinefunction(cp.request):
                decision = await cp.request(state, artifacts)
            else:
                decision = await asyncio.to_thread(cp.request, state, artifacts)

            await _emit(ctx, {
                "type": "checkpoint_resolved",
                "stage": stage.name,
                "decision": decision.value,
            })
            if decision == Decision.REJECT:
                raise RuntimeError(f"Stage '{stage.name}' rejected at human checkpoint.")

        return state


async def _emit(ctx: Context, event: dict) -> None:
    if ctx.on_event:
        await ctx.on_event(event)
