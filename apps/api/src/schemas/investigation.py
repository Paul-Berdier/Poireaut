"""Investigation I/O schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.db.types import AutoPivotMode, InvestigationStatus


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class InvestigationUpdate(BaseModel):
    """Patch existing investigation. All fields optional — only sent ones change."""
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    status: InvestigationStatus | None = None
    # Auto-pivot settings — surfaced in the UI's settings panel
    auto_pivot_mode: AutoPivotMode | None = None
    auto_pivot_min_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to trigger auto-pivot (0.0–1.0)",
    )
    auto_pivot_max_depth: int | None = Field(
        default=None,
        ge=0,
        le=10,
        description="Max auto-pivot chain depth (0–10, hard cap at 10)",
    )


class InvestigationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: InvestigationStatus
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    # Auto-pivot settings (always returned so the UI can render the settings panel)
    auto_pivot_mode: AutoPivotMode
    auto_pivot_min_confidence: float
    auto_pivot_max_depth: int
