"""Sentry SDK initialization helpers for the FastAPI backend.

This module has no import of src.api.database so it can be safely imported
in unit tests without a DATABASE_URL being set.
"""

import logging
import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger(__name__)


def _traces_sampler(sampling_context: dict) -> float:
    """Return 0 for /health transactions; otherwise use the configured rate.

    Reads SENTRY_TRACES_SAMPLE_RATE on each call. Falls back to 1.0 and logs
    a warning if the value is not a valid float. Clamps the result to [0.0, 1.0].
    """
    asgi_scope = sampling_context.get("asgi_scope", {})
    path = asgi_scope.get("path", "")
    if path == "/health":
        return 0.0
    try:
        rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0"))
    except ValueError:
        logger.warning(
            "SENTRY_TRACES_SAMPLE_RATE is not a valid float; defaulting to 1.0"
        )
        rate = 1.0
    return max(0.0, min(1.0, rate))


def _init_sentry(
    dsn: str | None,
    environment: str,
    traces_sampler: object = _traces_sampler,
) -> None:
    """Read SENTRY_DSN from env and initialize the Sentry SDK.

    No-ops when dsn is empty so local dev without a Sentry project works.
    Called from src.api.main at module load time, before create_app().
    """
    if not dsn:
        logger.debug("SENTRY_DSN is not set; Sentry will not be initialized.")
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sampler=traces_sampler,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        send_default_pii=False,
    )
    logger.info("Sentry initialized (environment=%s).", environment)
