"""Connectors listing endpoint + run history + manual healthcheck trigger.

Returns every connector known to the DB (populated the first time the worker
runs one). Lets the UI show which tools are available and their health.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select

from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
    RunStatus,
)
from src.deps import CurrentUser, DbSession
from src.models.connector import Connector, ConnectorRun
from src.services.celery_producer import celery

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


class ConnectorRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connector_id: uuid.UUID
    input_datapoint_id: uuid.UUID | None
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    result_count: int
    error_message: str | None
    created_at: datetime


class HealthcheckResponse(BaseModel):
    task_id: str
    message: str


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(user: CurrentUser, db: DbSession) -> list[Connector]:
    stmt = select(Connector).order_by(Connector.category, Connector.name)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{connector_id}/runs", response_model=list[ConnectorRunOut])
async def list_connector_runs(
    connector_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = 20,
) -> list[ConnectorRun]:
    """Last N runs of a connector, newest first. Useful to inspect errors."""
    limit = max(1, min(100, limit))
    stmt = (
        select(ConnectorRun)
        .where(ConnectorRun.connector_id == connector_id)
        .order_by(desc(ConnectorRun.created_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("/healthcheck", response_model=HealthcheckResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_healthcheck(user: CurrentUser) -> HealthcheckResponse:
    """Manually enqueue a healthcheck run (same task as the daily schedule)."""
    # Only admins should do this in production, but for v0.5 any authed user can.
    result = celery.send_task("src.tasks.healthcheck_all_connectors")
    return HealthcheckResponse(
        task_id=result.id,
        message="Healthcheck en cours. Résultats disponibles dans ~30s.",
    )
