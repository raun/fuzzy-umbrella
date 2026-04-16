"""End-to-end integration tests for the items endpoints against real Postgres.

These tests are skipped automatically when TEST_DATABASE_URL is not set in the
environment.  See tests/integration/conftest.py for fixture details.
"""

import pytest
from httpx import AsyncClient

from tests.integration.conftest import skip_integration


pytestmark = skip_integration


@pytest.mark.asyncio
async def test_integration_create_and_list_item(integration_client: AsyncClient) -> None:
    """Creating an item via POST then fetching it via GET /api/items works end-to-end."""
    create_resp = await integration_client.post(
        "/api/items",
        json={"name": "Integration Widget", "description": "Real DB"},
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    list_resp = await integration_client.get("/api/items")
    assert list_resp.status_code == 200
    ids = [item["id"] for item in list_resp.json()]
    assert item_id in ids


@pytest.mark.asyncio
async def test_integration_get_single_item(integration_client: AsyncClient) -> None:
    """After creating an item, GET /api/items/{id} returns the correct item."""
    create_resp = await integration_client.post(
        "/api/items",
        json={"name": "Single fetch", "description": "desc here"},
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    get_resp = await integration_client.get(f"/api/items/{item_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == item_id
    assert body["name"] == "Single fetch"
    assert body["description"] == "desc here"
    # created_at must be a non-empty ISO-8601 string
    assert isinstance(body["created_at"], str) and body["created_at"]


@pytest.mark.asyncio
async def test_integration_delete_item(integration_client: AsyncClient) -> None:
    """Deleting an item returns 204 and subsequent GET returns 404."""
    create_resp = await integration_client.post(
        "/api/items",
        json={"name": "Delete in integration"},
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    del_resp = await integration_client.delete(f"/api/items/{item_id}")
    assert del_resp.status_code == 204
    assert del_resp.content == b""

    get_resp = await integration_client.get(f"/api/items/{item_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_integration_get_nonexistent_item(integration_client: AsyncClient) -> None:
    """GET /api/items/{id} for an id that does not exist returns 404 with detail."""
    response = await integration_client.get("/api/items/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "detail" in response.json()
