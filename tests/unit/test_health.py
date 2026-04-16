"""Tests for GET /health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health must return HTTP 200."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_ok_body(client: AsyncClient) -> None:
    """GET /health must return JSON body {"status": "ok"}."""
    response = await client.get("/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_content_type_is_json(client: AsyncClient) -> None:
    """GET /health must respond with application/json content-type."""
    response = await client.get("/health")
    assert "application/json" in response.headers["content-type"]
