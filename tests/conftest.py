"""Pytest fixtures for Mandrel tests.

The `db_session` fixture requires a live Postgres instance at
MANDREL_DATABASE_URL (default: localhost:5432). In CI this is provided by a
GitHub Actions `services:` block. Locally, `docker compose up -d postgres`.

Integration tests that use db_session are marked with @pytest.mark.integration
so they can be skipped without a running database:
    pytest -m "not integration"
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

# Pull in table definitions so metadata is populated
from mandrel.db.models import DesignStateRecord  # noqa: F401


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: tests that require a live Postgres instance")


@pytest.fixture(scope="session")
def db_url() -> str:
    return os.getenv(
        "MANDREL_DATABASE_URL",
        "postgresql+asyncpg://mandrel:mandrel@localhost:5432/mandrel",
    )


@pytest_asyncio.fixture(scope="session")
async def db_engine(db_url):
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()
