"""FastAPI application factory.

Schema must exist via `alembic upgrade head` before the server starts.
This module does NOT call Base.metadata.create_all.
"""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import health, items
from src.api.sentry_utils import _init_sentry, _traces_sampler

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
    application = FastAPI(title="fuzzy-umbrella API")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(items.router)

    return application


app = create_app()
