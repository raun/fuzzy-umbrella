"""FastAPI application factory.

Schema must exist via `alembic upgrade head` before the server starts.
This module does NOT call Base.metadata.create_all.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import health, items, whatsapp
from src.api.sentry_utils import _init_sentry, _traces_sampler
from src.api.services.agent_config import load_all_knowledge_bases

logger = logging.getLogger(__name__)

_init_sentry(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
    traces_sampler=_traces_sampler,
)


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI application instance.

    Does not call Base.metadata.create_all. Schema must exist via
    `alembic upgrade head` before any requests are handled.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[type-arg]
        """Run startup tasks: fetch and cache all agent knowledge bases in parallel."""
        await load_all_knowledge_bases()
        yield

    application = FastAPI(title="fuzzy-umbrella API", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(items.router)
    application.include_router(whatsapp.router)

    return application


app = create_app()
