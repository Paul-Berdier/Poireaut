"""Investigations CRUD. Every route is scoped to the current user —
nobody can list, read, modify or delete someone else's enquête.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import CurrentUser, DbSession
from src.models.investigation import Investigation
from src.models.user import User
from src.schemas.investigation import (
    InvestigationCreate,
    InvestigationOut,
    InvestigationUpdate,
)

router = APIRouter(prefix="/investigations", tags=["investigations"])


async def _get_owned(
    db: AsyncSession, investigation_id: uuid.UUID, user: User
) -> Investigation:
    inv = await db.get(Investigation, investigation_id)
    if inv is None or inv.owner_id != user.id:
        # 404 (not 403) to avoid leaking existence of other users' cases.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return inv


@router.get("", response_model=list[InvestigationOut])
async def list_investigations(user: CurrentUser, db: DbSession) -> list[Investigation]:
    stmt = (
        select(Investigation)
        .where(Investigation.owner_id == user.id)
        .order_by(Investigation.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "",
    response_model=InvestigationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_investigation(
    payload: InvestigationCreate,
    user: CurrentUser,
    db: DbSession,
) -> Investigation:
    inv = Investigation(
        title=payload.title,
        description=payload.description,
        owner_id=user.id,
    )
    db.add(inv)
    await db.flush()
    await db.refresh(inv)
    return inv


@router.get("/{investigation_id}", response_model=InvestigationOut)
async def get_investigation(
    investigation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Investigation:
    return await _get_owned(db, investigation_id, user)


@router.patch("/{investigation_id}", response_model=InvestigationOut)
async def update_investigation(
    investigation_id: uuid.UUID,
    payload: InvestigationUpdate,
    user: CurrentUser,
    db: DbSession,
) -> Investigation:
    inv = await _get_owned(db, investigation_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(inv, field, value)
    await db.flush()
    await db.refresh(inv)
    return inv


@router.delete(
    "/{investigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_investigation(
    investigation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    inv = await _get_owned(db, investigation_id, user)
    await db.delete(inv)
