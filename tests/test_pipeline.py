"""Phase 0 acceptance tests.

Pass criteria (from SPEC.md §9):
  - Empty pipeline runs end-to-end with no-op stages.
  - DesignState persists and round-trips through Postgres.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mandrel.core.state import Constraints, DesignState, FormFactor
from mandrel.core.workflow import Context, PipelineRunner
from mandrel.pipeline.noop import NoopStage

# ── Pipeline execution tests (no DB required) ─────────────────────────────────


@pytest.mark.asyncio
async def test_empty_pipeline_returns_state(tmp_path: Path) -> None:
    """An empty pipeline returns the input state unchanged."""
    state = DesignState()
    runner = PipelineRunner(stages=[])
    ctx = Context(project_dir=tmp_path)

    result = await runner.run(state, ctx)

    assert result.project_id == state.project_id
    assert result.history == []


@pytest.mark.asyncio
async def test_noop_stage_records_history(tmp_path: Path) -> None:
    """A NoopStage runs without error and appends one StageRun to history."""
    state = DesignState()
    runner = PipelineRunner(stages=[NoopStage("s0_noop")])
    ctx = Context(project_dir=tmp_path)

    result = await runner.run(state, ctx)

    assert len(result.history) == 1
    run = result.history[0]
    assert run.stage_name == "s0_noop"
    assert run.success is True
    assert run.completed_at is not None
    assert run.verifier_result is not None
    assert run.verifier_result.passed is True


@pytest.mark.asyncio
async def test_multiple_noop_stages_ordered(tmp_path: Path) -> None:
    """Multiple no-op stages run in order and all appear in history."""
    stages = [NoopStage(f"s{i}") for i in range(3)]
    runner = PipelineRunner(stages=stages)
    state = DesignState()
    ctx = Context(project_dir=tmp_path)

    result = await runner.run(state, ctx)

    assert [r.stage_name for r in result.history] == ["s0", "s1", "s2"]
    assert all(r.success for r in result.history)


@pytest.mark.asyncio
async def test_state_constraints_preserved(tmp_path: Path) -> None:
    """Constraints on the input state survive a pipeline run unchanged."""
    state = DesignState(constraints=Constraints(form_factor=FormFactor.FEATHER))
    runner = PipelineRunner(stages=[NoopStage("check")])
    ctx = Context(project_dir=tmp_path)

    result = await runner.run(state, ctx)

    assert result.constraints.form_factor == FormFactor.FEATHER


# ── DB round-trip tests (require live Postgres) ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_design_state_roundtrip(db_session, tmp_path: Path) -> None:
    """DesignState saves to Postgres and loads back with identical field values."""
    from mandrel.db.repository import StateRepository

    state = DesignState(constraints=Constraints(form_factor=FormFactor.DIN_RAIL))
    repo = StateRepository(db_session)

    await repo.save(state)
    loaded = await repo.load(state.project_id)

    assert loaded.project_id == state.project_id
    assert loaded.spec is None
    assert loaded.constraints.form_factor == FormFactor.DIN_RAIL
    assert loaded.history == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pipeline_state_persists_after_run(db_session, tmp_path: Path) -> None:
    """State produced by a pipeline run persists and round-trips through DB."""
    from mandrel.db.repository import StateRepository

    state = DesignState()
    runner = PipelineRunner(stages=[NoopStage("s0"), NoopStage("s1")])
    ctx = Context(project_dir=tmp_path)

    result = await runner.run(state, ctx)

    repo = StateRepository(db_session)
    await repo.save(result)
    loaded = await repo.load(result.project_id)

    assert loaded.project_id == result.project_id
    assert len(loaded.history) == 2
    assert loaded.history[0].stage_name == "s0"
    assert loaded.history[1].stage_name == "s1"
    assert all(r.success for r in loaded.history)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_state_upsert_updates_existing(db_session, tmp_path: Path) -> None:
    """Saving a state twice upserts — the second save overwrites the first."""
    from mandrel.db.repository import StateRepository

    state = DesignState()
    repo = StateRepository(db_session)

    await repo.save(state)

    # Mutate and save again
    runner = PipelineRunner(stages=[NoopStage("extra")])
    ctx = Context(project_dir=tmp_path)
    updated = await runner.run(state, ctx)
    await repo.save(updated)

    loaded = await repo.load(state.project_id)
    assert len(loaded.history) == 1
    assert loaded.history[0].stage_name == "extra"
