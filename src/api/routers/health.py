"""Health check router."""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}
