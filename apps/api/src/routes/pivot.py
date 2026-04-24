"""Pivot endpoint — run every compatible connector against a DataPoint.

POST /datapoints/{id}/pivot → enqueue a worker task, return 202 + task_id.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import CurrentUser, DbSession
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation
from src.models.user import User
from src.services.celery_producer import enqueue_pivot

router = APIRouter(tags=["pivot"])


class PivotResponse(BaseModel):
    task_id: str
    datapoint_id: uuid.UUID
    message: str


async def _check_ownership(
    db: AsyncSession, datapoint_id: uuid.UUID, user: User
) -> DataPoint:
    dp = await db.get(DataPoint, datapoint_id)
    if dp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    entity = await db.get(Entity, dp.entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    inv = await db.get(Investigation, entity.investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return dp


@router.post(
    "/datapoints/{datapoint_id}/pivot",
    response_model=PivotResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def pivot(
    datapoint_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> PivotResponse:
    """Queue a pivot job. Subscribe to /ws/investigations/{id} to see results land."""
    await _check_ownership(db, datapoint_id, user)
    task_id = enqueue_pivot(str(datapoint_id))
    return PivotResponse(
        task_id=task_id,
        datapoint_id=datapoint_id,
        message="Pivot queued. Mr. Poireaut is tugging on threads.",
    )
