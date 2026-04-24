"""Connectors listing endpoint.

Returns every connector known to the DB (populated the first time the worker
runs one). Lets the UI show which tools are available and their health.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
)
from src.deps import CurrentUser, DbSession
from src.models.connector import Connector

router = APIRouter(prefix="/connectors", tags=["connectors"])


class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    category: ConnectorCategory
    description: str | None
    homepage_url: str | None
    input_types: list[DataType]
    output_types: list[DataType]
    cost: ConnectorCost
    health: HealthStatus
    last_health_check: datetime | None
    enabled: bool


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(user: CurrentUser, db: DbSession) -> list[Connector]:
    stmt = select(Connector).order_by(Connector.category, Connector.name)
    return list((await db.execute(stmt)).scalars().all())
