"""Unit tests for the /api/items CRUD endpoints.

All tests use the in-memory SQLite database and the overridden get_db
dependency provided by tests/unit/conftest.py.  No real Postgres connection
is required.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /api/items — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_empty_initially(client: AsyncClient) -> None:
    """GET /api/items must return an empty list when no items exist."""
    response = await client.get("/api/items")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_items_returns_all_created_items(client: AsyncClient) -> None:
    """GET /api/items returns every item after two items are created."""
    await client.post("/api/items", json={"name": "Alpha"})
    await client.post("/api/items", json={"name": "Beta"})

    response = await client.get("/api/items")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    names = {item["name"] for item in items}
    assert names == {"Alpha", "Beta"}


# ---------------------------------------------------------------------------
# POST /api/items — create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_item_returns_201(client: AsyncClient) -> None:
    """POST /api/items must return HTTP 201 Created."""
    response = await client.post("/api/items", json={"name": "Widget"})
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_item_response_shape(client: AsyncClient) -> None:
    """POST /api/items response body must contain id, name, description, created_at."""
    response = await client.post(
        "/api/items",
        json={"name": "Widget", "description": "A fine widget"},
    )
    body = response.json()
    assert "id" in body
    assert body["name"] == "Widget"
    assert body["description"] == "A fine widget"
    assert "created_at" in body
    # created_at must be a non-empty ISO-8601 string
    assert isinstance(body["created_at"], str) and body["created_at"]


@pytest.mark.asyncio
async def test_create_item_id_is_string(client: AsyncClient) -> None:
    """POST /api/items must return a non-empty string id."""
    response = await client.post("/api/items", json={"name": "Widget"})
    body = response.json()
    assert isinstance(body["id"], str)
    assert len(body["id"]) > 0


@pytest.mark.asyncio
async def test_create_item_without_description_sets_null(client: AsyncClient) -> None:
    """POST /api/items with no description field sets description to null."""
    response = await client.post("/api/items", json={"name": "NullDesc"})
    assert response.status_code == 201
    assert response.json()["description"] is None


@pytest.mark.asyncio
async def test_create_item_with_explicit_null_description(client: AsyncClient) -> None:
    """POST /api/items with description=null explicitly sets description to null."""
    response = await client.post(
        "/api/items",
        json={"name": "ExplicitNull", "description": None},
    )
    assert response.status_code == 201
    assert response.json()["description"] is None


@pytest.mark.asyncio
async def test_create_item_name_too_long_returns_422(client: AsyncClient) -> None:
    """POST /api/items with name longer than 200 characters must return 422."""
    long_name = "x" * 201
    response = await client.post("/api/items", json={"name": long_name})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_item_description_too_long_returns_422(client: AsyncClient) -> None:
    """POST /api/items with description longer than 2000 characters must return 422."""
    response = await client.post(
        "/api/items",
        json={"name": "ok", "description": "d" * 2001},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_item_empty_name_returns_422(client: AsyncClient) -> None:
    """POST /api/items with empty name must return 422 (min_length=1)."""
    response = await client.post("/api/items", json={"name": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_item_missing_name_returns_422(client: AsyncClient) -> None:
    """POST /api/items with missing name field must return 422."""
    response = await client.post("/api/items", json={"description": "No name"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/items/{id} — retrieve single item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_item_returns_created_item(client: AsyncClient) -> None:
    """GET /api/items/{id} returns the item that was just created."""
    create_resp = await client.post(
        "/api/items",
        json={"name": "Retrieve me", "description": "hello"},
    )
    item_id = create_resp.json()["id"]

    response = await client.get(f"/api/items/{item_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == item_id
    assert body["name"] == "Retrieve me"
    assert body["description"] == "hello"


@pytest.mark.asyncio
async def test_get_item_unknown_id_returns_404(client: AsyncClient) -> None:
    """GET /api/items/{id} with a non-existent id must return 404."""
    response = await client.get("/api/items/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_item_404_detail_message(client: AsyncClient) -> None:
    """GET /api/items/{id} 404 response must contain a 'detail' key."""
    response = await client.get("/api/items/ghost")
    body = response.json()
    assert "detail" in body


# ---------------------------------------------------------------------------
# DELETE /api/items/{id} — delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_item_returns_204(client: AsyncClient) -> None:
    """DELETE /api/items/{id} must return HTTP 204 No Content."""
    create_resp = await client.post("/api/items", json={"name": "Delete me"})
    item_id = create_resp.json()["id"]

    response = await client.delete(f"/api/items/{item_id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_item_response_body_is_empty(client: AsyncClient) -> None:
    """DELETE /api/items/{id} 204 response must have no body content."""
    create_resp = await client.post("/api/items", json={"name": "Empty body"})
    item_id = create_resp.json()["id"]

    response = await client.delete(f"/api/items/{item_id}")
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_delete_item_removes_it_from_list(client: AsyncClient) -> None:
    """After DELETE, the item must no longer appear in GET /api/items."""
    create_resp = await client.post("/api/items", json={"name": "Gone soon"})
    item_id = create_resp.json()["id"]

    await client.delete(f"/api/items/{item_id}")

    list_resp = await client.get("/api/items")
    ids = [item["id"] for item in list_resp.json()]
    assert item_id not in ids


@pytest.mark.asyncio
async def test_delete_item_removes_it_from_get(client: AsyncClient) -> None:
    """After DELETE, GET /api/items/{id} must return 404."""
    create_resp = await client.post("/api/items", json={"name": "Gone soon"})
    item_id = create_resp.json()["id"]

    await client.delete(f"/api/items/{item_id}")

    get_resp = await client.get(f"/api/items/{item_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_item_unknown_id_returns_404(client: AsyncClient) -> None:
    """DELETE /api/items/{id} with a non-existent id must return 404."""
    response = await client.delete("/api/items/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_item_unknown_id_detail_message(client: AsyncClient) -> None:
    """DELETE /api/items/{id} 404 response must contain a 'detail' key."""
    response = await client.delete("/api/items/ghost")
    body = response.json()
    assert "detail" in body


# ---------------------------------------------------------------------------
# Parameterised: create multiple items, verify list length
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "items_to_create",
    [
        [{"name": "One"}, {"name": "Two"}],
        [{"name": "A"}, {"name": "B"}, {"name": "C"}],
    ],
    ids=["two-items", "three-items"],
)
async def test_list_items_count_matches_created(
    client: AsyncClient, items_to_create: list[dict]
) -> None:
    """GET /api/items returns a list whose length equals the number of created items."""
    for payload in items_to_create:
        resp = await client.post("/api/items", json=payload)
        assert resp.status_code == 201

    list_resp = await client.get("/api/items")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == len(items_to_create)
