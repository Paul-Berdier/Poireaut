"""Entity I/O schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.db.types import EntityRole


class EntityCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    role: EntityRole = EntityRole.TARGET
    notes: str | None = Field(default=None, max_length=10_000)


class EntityUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: EntityRole | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    investigation_id: uuid.UUID
    display_name: str
    role: EntityRole
    notes: str | None
    created_at: datetime
    updated_at: datetime
