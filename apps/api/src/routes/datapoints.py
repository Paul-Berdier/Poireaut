"""DataPoint routes.

POST   /entities/{id}/datapoints     — manual insertion by investigator
GET    /entities/{id}/datapoints     — list for entity
GET    /datapoints/{id}              — single
PATCH  /datapoints/{id}              — validate / reject / set confidence / notes
DELETE /datapoints/{id}              — remove
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.types import VerificationStatus
from src.deps import CurrentUser, DbSession
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation
from src.models.user import User
from src.schemas.datapoint import (
    DataPointCreate,
    DataPointOut,
    DataPointUpdate,
)

router = APIRouter(tags=["datapoints"])


async def _get_owned_entity(db: AsyncSession, entity_id: uuid.UUID, user: User) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    inv = await db.get(Investigation, entity.investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return entity


async def _get_owned_datapoint(
    db: AsyncSession, datapoint_id: uuid.UUID, user: User
) -> DataPoint:
    dp = await db.get(DataPoint, datapoint_id)
    if dp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await _get_owned_entity(db, dp.entity_id, user)  # ownership check
    return dp


@router.get(
    "/entities/{entity_id}/datapoints",
    response_model=list[DataPointOut],
)
async def list_datapoints(
    entity_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[DataPoint]:
    await _get_owned_entity(db, entity_id, user)
    stmt = (
        select(DataPoint)
        .where(DataPoint.entity_id == entity_id)
        .order_by(DataPoint.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/entities/{entity_id}/datapoints",
    response_model=DataPointOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_datapoint(
    entity_id: uuid.UUID,
    payload: DataPointCreate,
    user: CurrentUser,
    db: DbSession,
) -> DataPoint:
    """Manual insertion. Auto-validated because the investigator typed it in."""
    await _get_owned_entity(db, entity_id, user)
    dp = DataPoint(
        entity_id=entity_id,
        type=payload.type,
        value=payload.value.strip(),
        status=VerificationStatus.VALIDATED,
        confidence=payload.confidence if payload.confidence is not None else 1.0,
        notes=payload.notes,
        validated_at=datetime.now(timezone.utc),
        validated_by=user.id,
    )
    db.add(dp)
    await db.flush()
    await db.refresh(dp)
    return dp


@router.get("/datapoints/{datapoint_id}", response_model=DataPointOut)
async def get_datapoint(
    datapoint_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DataPoint:
    return await _get_owned_datapoint(db, datapoint_id, user)


@router.patch("/datapoints/{datapoint_id}", response_model=DataPointOut)
async def update_datapoint(
    datapoint_id: uuid.UUID,
    payload: DataPointUpdate,
    user: CurrentUser,
    db: DbSession,
) -> DataPoint:
    dp = await _get_owned_datapoint(db, datapoint_id, user)

    data = payload.model_dump(exclude_unset=True)

    # Audit the validation transition
    if "status" in data and data["status"] != dp.status:
        dp.status = data.pop("status")
        if dp.status == VerificationStatus.VALIDATED:
            dp.validated_at = datetime.now(timezone.utc)
            dp.validated_by = user.id
        elif dp.status == VerificationStatus.REJECTED:
            dp.validated_at = datetime.now(timezone.utc)
            dp.validated_by = user.id
        else:
            dp.validated_at = None
            dp.validated_by = None

    for field, value in data.items():
        setattr(dp, field, value)

    await db.flush()
    await db.refresh(dp)
    return dp


@router.delete(
    "/datapoints/{datapoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_datapoint(
    datapoint_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    dp = await _get_owned_datapoint(db, datapoint_id, user)
    await db.delete(dp)
