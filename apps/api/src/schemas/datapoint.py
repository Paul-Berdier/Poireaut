"""DataPoint I/O schemas + graph projection."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.db.types import DataType, VerificationStatus


class DataPointCreate(BaseModel):
    """Manual insertion of a datapoint by the investigator."""

    type: DataType
    value: str = Field(min_length=1, max_length=4096)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=10_000)


class DataPointUpdate(BaseModel):
    status: VerificationStatus | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=10_000)


class DataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_id: uuid.UUID
    type: DataType
    value: str
    status: VerificationStatus
    confidence: float | None

    source_connector_id: uuid.UUID | None
    source_datapoint_id: uuid.UUID | None
    source_url: str | None
    raw_data: dict[str, Any] | None

    extracted_at: datetime | None
    validated_at: datetime | None
    validated_by: uuid.UUID | None
    notes: str | None

    created_at: datetime
    updated_at: datetime


# ─── Graph projection (what the spider-web UI consumes) ──────────────────

class GraphNode(BaseModel):
    id: uuid.UUID
    kind: str                        # "entity" | "datapoint"
    label: str
    data_type: DataType | None = None
    status: VerificationStatus | None = None
    confidence: float | None = None


class GraphEdge(BaseModel):
    id: str                          # synthetic, e.g. "dp-{src}-{dst}"
    source: uuid.UUID
    target: uuid.UUID
    connector_name: str | None = None
    kind: str = "pivot"              # "pivot" | "owns" (entity→datapoint)


class GraphOut(BaseModel):
    investigation_id: uuid.UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
