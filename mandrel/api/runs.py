"""In-memory run store and per-run context for WebSocket event fan-out.

Each run is identified by a UUID run_id. The RunContext tracks:
  - event history (replayed to new WS subscribers so they see prior events)
  - a broadcast queue per subscriber
  - an asyncio.Event used to gate pipeline execution at checkpoints

The WebSocket handler subscribes on connect, receives replayed history,
then blocks on new events. POST /approve or /reject resolves the checkpoint.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class RunContext:
    run_id: str
    project_id: str
    event_history: list[dict] = field(default_factory=list)
    _subscribers: list[asyncio.Queue] = field(default_factory=list)
    # checkpoint gate: set when a checkpoint decision has been made
    checkpoint_event: asyncio.Event = field(default_factory=asyncio.Event)
    checkpoint_decision: str | None = None  # "approve" | "reject"
    # overall run state
    status: str = "running"  # running | completed | failed
    error: str | None = None

    async def emit(self, event: dict) -> None:
        """Append event to history and broadcast to all subscribers."""
        self.event_history.append(event)
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        # Replay history so new subscribers see what already happened
        for ev in self.event_history:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                break
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def wait_for_checkpoint(self) -> str:
        """Block until approve/reject is posted. Returns the decision string."""
        await self.checkpoint_event.wait()
        self.checkpoint_event.clear()
        return self.checkpoint_decision or "approve"

    def resolve_checkpoint(self, decision: str) -> None:
        self.checkpoint_decision = decision
        self.checkpoint_event.set()


class RunStore:
    """Thread-safe in-memory store of active RunContexts."""

    def __init__(self) -> None:
        self._runs: dict[str, RunContext] = {}

    def create(self, run_id: str, project_id: str) -> RunContext:
        ctx = RunContext(run_id=run_id, project_id=project_id)
        self._runs[run_id] = ctx
        return ctx

    def get(self, run_id: str) -> RunContext | None:
        return self._runs.get(run_id)

    def list_ids(self) -> list[str]:
        return list(self._runs.keys())
