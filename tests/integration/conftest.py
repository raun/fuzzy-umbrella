"""Integration-test fixtures.

These fixtures require a real PostgreSQL server.  Set the environment variable
TEST_DATABASE_URL to a connection string for the test database, e.g.

    TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/appdb_test

All tests in this package are skipped automatically when TEST_DATABASE_URL is
not set.

The `setup_test_db` fixture:
  1. Creates the `appdb_test` database via asyncpg (catches DuplicateDatabaseError).
  2. Runs `alembic upgrade head` in a ThreadPoolExecutor so that asyncio.run()
     inside Alembic's env.py does not raise RuntimeError from being called
     inside an already-running event loop.
  3. Yields so the test can run.
  4. Runs `alembic downgrade base` to wipe schema.
  5. Drops the `appdb_test` database.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator
from urllib.parse import urlparse

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Skip all integration tests when TEST_DATABASE_URL is not set.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL: str | None = os.environ.get("TEST_DATABASE_URL")

skip_integration = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set — skipping integration tests",
)


def _parse_admin_dsn(test_url: str) -> tuple[str, str]:
    """Return (admin_dsn, db_name) parsed from *test_url*.

    The admin DSN points at the `postgres` maintenance database on the same
    server so we can issue CREATE/DROP DATABASE statements.
    """
    parsed = urlparse(test_url)
    db_name = parsed.path.lstrip("/")  # e.g. "appdb_test"
    # Replace the path with /postgres to get the admin connection string.
    admin_dsn = parsed._replace(
        # asyncpg uses "postgresql://" not "postgresql+asyncpg://"
        scheme="postgresql",
        path="/postgres",
    ).geturl()
    return admin_dsn, db_name


# ---------------------------------------------------------------------------
# Database setup / teardown
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_test_db() -> AsyncGenerator[str, None]:
    """Create the test database, run migrations, yield the URL, then teardown."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")

    import asyncpg  # type: ignore[import-untyped]

    admin_dsn, db_name = _parse_admin_dsn(TEST_DATABASE_URL)

    # --- Create test database -------------------------------------------------
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    except asyncpg.exceptions.DuplicateDatabaseError:
        pass  # already exists — that is fine
    finally:
        await conn.close()

    # --- Run alembic upgrade head in a thread so asyncio.run() in env.py ------
    # --- does not conflict with the running event loop. -----------------------
    def _alembic_upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
        command.upgrade(cfg, "head")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        await loop.run_in_executor(executor, _alembic_upgrade)

    yield TEST_DATABASE_URL

    # --- Teardown: downgrade then drop ----------------------------------------
    def _alembic_downgrade() -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
        command.downgrade(cfg, "base")

    with ThreadPoolExecutor(max_workers=1) as executor:
        await loop.run_in_executor(executor, _alembic_downgrade)

    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Per-test HTTP client wired to the real Postgres database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def integration_client(setup_test_db: str) -> AsyncGenerator:
    """AsyncClient whose FastAPI app uses the real test Postgres database.

    The DATABASE_URL environment variable is temporarily set to the test
    database URL so that the engine created in database.py connects to the
    right server.  A fresh engine (and therefore fresh connection pool) is
    created for each test to prevent state bleed.
    """
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.api.database import get_db
    from src.api.main import app

    engine = create_async_engine(setup_test_db, echo=False)
    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
