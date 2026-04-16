"""Pydantic v2 request/response schemas for the API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemCreate(BaseModel):
    """Schema for creating a new item."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ItemResponse(BaseModel):
    """Schema for returning an item in API responses."""

    model_config = ConfigDict(from_attributes=True)
    # Required so FastAPI can serialize SQLAlchemy ORM objects directly.
    # Without this, calling ItemResponse.model_validate(orm_obj) raises
    # ValidationError at runtime because Pydantic cannot read ORM attributes.

    id: str
    name: str
    description: str | None
    created_at: datetime
