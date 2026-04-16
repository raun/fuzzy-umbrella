"""Async SQLAlchemy engine, session factory, and FastAPI dependency for database access."""

import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Set it to a valid async SQLAlchemy connection string, e.g. "
        "postgresql+asyncpg://user:password@localhost:5432/appdb"
    )

async_engine = create_async_engine(_DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a per-request async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        yield session
