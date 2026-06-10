"""SQLModel table definitions for Mandrel's Postgres store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DesignStateRecord(SQLModel, table=True):
    """Persisted snapshot of a DesignState.

    Each write is an upsert on project_id (latest-wins semantics for Phase 0).
    The full DesignState JSON is stored in the `state` JSONB column.
    """

    __tablename__ = "design_states"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    project_id: str = Field(unique=True)
    state: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
