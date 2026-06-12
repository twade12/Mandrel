"""FastAPI application — REST + WebSocket API for the Mandrel pipeline.

Routes:
  POST /api/runs                         — start a new pipeline run
  GET  /api/runs/{run_id}                — get run status + event history
  WS   /api/runs/{run_id}/ws             — subscribe to real-time events
  POST /api/runs/{run_id}/checkpoint     — approve or reject the pending checkpoint
  GET  /                                  — serve the SPA (mandrel/ui/index.html)

WebSocket event types (sent server→client):
  stage_started       {stage, label}
  stage_progress      {stage, message, detail?}   (detail = live LLM output tail)
  stage_completed     {stage, label, passed, score, violations, state}
  stage_failed        {stage, label, error}
  checkpoint_needed   {stage, label, summary, state}
  checkpoint_resolved {stage, decision}
  run_completed       {state}
  run_failed          {error}
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .runs import RunStore

_store = RunStore()
_UI_HTML = Path(__file__).parent.parent / "ui" / "index.html"

app = FastAPI(title="Mandrel", version="0.1.0")


# ── Request / response models ──────────────────────────────────────────────────


class StartRunRequest(BaseModel):
    brief: str
    form_factor: str = "feather"
    auto_approve: bool = False
    llm_model: str | None = None


class CheckpointRequest(BaseModel):
    decision: str  # "approve" | "reject"


# ── Background pipeline task ───────────────────────────────────────────────────


async def _run_pipeline(run_id: str, req: StartRunRequest) -> None:
    from mandrel.config import settings
    from mandrel.core.checkpoints import AutoApproveCheckpoint
    from mandrel.core.state import Constraints, DesignState, FormFactor, ProductSpec
    from mandrel.core.workflow import Context, PipelineRunner
    from mandrel.llm.provider import OpenAICompatibleProvider
    from mandrel.pipeline.s1_intent import IntentStage
    from mandrel.pipeline.s2_architecture import ArchitectureStage
    from mandrel.pipeline.s3_schematic import SchematicStage
    from mandrel.pipeline.s4_layout import LayoutStage
    from mandrel.pipeline.s5_enclosure import EnclosureStage
    from mandrel.pipeline.s6_bom import BomStage

    run_ctx = _store.get(run_id)
    if run_ctx is None:
        return

    async def on_event(event: dict) -> None:
        await run_ctx.emit(event)

    model = req.llm_model or settings.llm_model
    llm = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=model,
        api_key=settings.llm_api_key,
        timeout_s=settings.llm_timeout_s,
    )

    form_factor = FormFactor(req.form_factor)
    state = DesignState(
        spec=ProductSpec(raw_brief=req.brief),
        constraints=Constraints(form_factor=form_factor),
    )

    project_dir = settings.workspace_dir / state.project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Update run_ctx with resolved project_id
    run_ctx.project_id = state.project_id

    # Build checkpoints — if auto_approve, use AutoApproveCheckpoint.
    # Otherwise use a WebSocket-gated checkpoint that awaits the POST /checkpoint
    # endpoint before the pipeline resumes.
    if req.auto_approve:
        checkpoints: dict[str, Any] = {
            "s1_intent":       AutoApproveCheckpoint(),
            "s2_architecture": AutoApproveCheckpoint(),
            "s3_schematic":    AutoApproveCheckpoint(),
            "s4_layout":       AutoApproveCheckpoint(),
            "s5_enclosure":    AutoApproveCheckpoint(),
            "s6_bom":          AutoApproveCheckpoint(),
        }
    else:
        cp = _WebCheckpoint(run_ctx)
        checkpoints = {
            "s1_intent":       cp,
            "s2_architecture": cp,
            "s3_schematic":    cp,
            "s4_layout":       cp,
            "s5_enclosure":    cp,
            "s6_bom":          cp,
        }

    runner = PipelineRunner(stages=[
        IntentStage(llm=llm),
        ArchitectureStage(llm=llm),
        SchematicStage(llm=llm),
        LayoutStage(llm=llm),
        EnclosureStage(),
        BomStage(),
    ], checkpoints=checkpoints)

    ctx = Context(project_dir=project_dir, config=settings, on_event=on_event)

    try:
        final_state = await runner.run(state, ctx)
        run_ctx.status = "completed"
        await run_ctx.emit({
            "type": "run_completed",
            "state": final_state.model_dump(mode="json"),
        })
    except Exception as exc:
        run_ctx.status = "failed"
        err_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        run_ctx.error = err_msg
        await run_ctx.emit({"type": "run_failed", "error": err_msg})
    finally:
        await llm.aclose()


class _WebCheckpoint:
    """Checkpoint implementation that suspends the pipeline until the user
    approves/rejects via POST /api/runs/{run_id}/checkpoint."""

    def __init__(self, run_ctx: Any) -> None:
        self._run_ctx = run_ctx

    async def request(self, state: Any, artifacts: list[Path]) -> Any:
        from mandrel.core.workflow import Decision
        decision_str = await self._run_ctx.wait_for_checkpoint()
        return Decision.APPROVE if decision_str == "approve" else Decision.REJECT


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.post("/api/runs")
async def start_run(req: StartRunRequest) -> JSONResponse:
    run_id = str(uuid.uuid4())
    _store.create(run_id, project_id="pending")
    asyncio.create_task(_run_pipeline(run_id, req))
    return JSONResponse({"run_id": run_id}, status_code=202)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    run_ctx = _store.get(run_id)
    if run_ctx is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse({
        "run_id": run_id,
        "project_id": run_ctx.project_id,
        "status": run_ctx.status,
        "error": run_ctx.error,
        "event_count": len(run_ctx.event_history),
    })


@app.post("/api/runs/{run_id}/checkpoint")
async def resolve_checkpoint(run_id: str, req: CheckpointRequest) -> JSONResponse:
    run_ctx = _store.get(run_id)
    if run_ctx is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")
    run_ctx.resolve_checkpoint(req.decision)
    return JSONResponse({"ok": True, "decision": req.decision})


@app.websocket("/api/runs/{run_id}/ws")
async def run_websocket(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    run_ctx = _store.get(run_id)
    if run_ctx is None:
        await websocket.send_json({"type": "error", "error": "Run not found"})
        await websocket.close(code=4004)
        return

    q = run_ctx.subscribe()
    try:
        while True:
            # Send any queued events to the client
            while not q.empty():
                event = q.get_nowait()
                await websocket.send_json(event)
                if event.get("type") in ("run_completed", "run_failed"):
                    return

            # Wait briefly for the next event or a client ping
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_json(event)
                if event.get("type") in ("run_completed", "run_failed"):
                    return
            except TimeoutError:
                # Send a keepalive ping
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    finally:
        run_ctx.unsubscribe(q)


@app.get("/")
async def serve_ui() -> FileResponse:
    if not _UI_HTML.exists():
        raise HTTPException(status_code=404, detail="UI not built")
    return FileResponse(_UI_HTML)
