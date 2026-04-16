"""Alembic environment configuration for async SQLAlchemy migrations."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic Config object — gives access to alembic.ini values
config = context.config

# Load the Alembic logging config from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ORM Base so Alembic can see all mapped tables for autogenerate
from src.api.db_models import Base  # noqa: E402
import src.api.db_models_whatsapp  # noqa: F401, E402

target_metadata = Base.metadata

# URL precedence: ini option first (allows programmatic override from conftest),
# then environment variable (used by CLI invocations where ini value is blank).
DATABASE_URL = config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live DB connection)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine.

    Both configure and run_migrations are wrapped in a single run_sync callback
    to ensure the sync connection state set by configure() remains valid when
    run_migrations() executes.
    """
    connectable = create_async_engine(DATABASE_URL)

    async with connectable.connect() as connection:

        def do_migrations(sync_conn: object) -> None:
            context.configure(
                connection=sync_conn,  # type: ignore[arg-type]
                target_metadata=target_metadata,
            )
            context.run_migrations()

        await connection.run_sync(do_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
