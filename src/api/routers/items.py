"""Items CRUD router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.database import get_db
from src.api.db_models import Item
from src.api.models import ItemCreate, ItemResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/items")


@router.get("", response_model=list[ItemResponse])
async def list_items(db: AsyncSession = Depends(get_db)) -> list[ItemResponse]:
    """Return all items."""
    result = await db.execute(select(Item))
    items = result.scalars().all()
    return [ItemResponse.model_validate(item) for item in items]


@router.post("", response_model=ItemResponse, status_code=201)
async def create_item(
    body: ItemCreate, db: AsyncSession = Depends(get_db)
) -> ItemResponse:
    """Create a new item and return it."""
    item = Item(name=body.name, description=body.description)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    logger.info("Created item id=%s name=%r", item.id, item.name)
    return ItemResponse.model_validate(item)


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str, db: AsyncSession = Depends(get_db)
) -> ItemResponse:
    """Return a single item by ID, or 404 if not found."""
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemResponse.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: str, db: AsyncSession = Depends(get_db)
) -> Response:
    """Delete an item by ID. Returns 204 on success, 404 if not found."""
    item = await db.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
    logger.info("Deleted item id=%s", item_id)
    return Response(status_code=204)
