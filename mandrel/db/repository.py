"""StateRepository: async CRUD for DesignState in Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mandrel.core.state import DesignState

from .models import DesignStateRecord


class StateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, state: DesignState) -> None:
        """Upsert DesignState by project_id (replace existing record)."""
        now = datetime.now(UTC)
        stmt = (
            insert(DesignStateRecord)
            .values(
                project_id=state.project_id,
                state=state.model_dump(mode="json"),
                created_at=state.created_at,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["project_id"],
                set_={"state": state.model_dump(mode="json"), "updated_at": now},
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def load(self, project_id: str) -> DesignState:
        """Load the most recent DesignState for a project_id. Raises if not found."""
        stmt = (
            select(DesignStateRecord)
            .where(DesignStateRecord.project_id == project_id)
            .order_by(DesignStateRecord.updated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise KeyError(f"No design state found for project_id={project_id!r}")
        return DesignState.model_validate(record.state)

    async def exists(self, project_id: str) -> bool:
        stmt = select(DesignStateRecord.id).where(
            DesignStateRecord.project_id == project_id
        ).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
