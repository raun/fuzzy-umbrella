"""Unit-test fixtures for the FastAPI application.

Uses an in-memory SQLite database via aiosqlite so that no external database
is required.  The `get_db` FastAPI dependency is overridden for every test, and
all ORM tables are created fresh before each test and dropped afterwards.
"""

import os

# Provide a dummy DATABASE_URL before any src.api modules are imported so that
# database.py does not raise RuntimeError at import time.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.database import get_db
from src.api.db_models import Base
import src.api.db_models_whatsapp  # noqa: F401
from src.api.main import app

# ---------------------------------------------------------------------------
# In-memory SQLite engine shared across all unit tests in a single session.
# Each test gets a fresh set of tables via the `db_session` fixture.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_TestSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create all ORM tables, yield a usable AsyncSession, then drop everything.

    Using ``create_all`` / ``drop_all`` around each test guarantees full
    isolation: no state leaks between tests even when they run in the same
    process with the same in-memory engine.
    """
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session = _TestSessionLocal()
    try:
        yield session
    finally:
        await session.close()
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncClient:
    """Return an AsyncClient whose `get_db` dependency is the test session.

    The override is registered on the FastAPI app instance and cleaned up after
    the test so that other tests are not affected.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
