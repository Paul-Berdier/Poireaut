"""Identity card endpoint.

Aggregates all the datapoints attached to an investigation's entities into
a structured "fiche identité" — the enquêteur's at-a-glance summary.

Unlike the raw datapoint list, this endpoint:
  * groups datapoints by type (all emails under `emails`, all photos under
    `photos`, …)
  * sorts within each group so the highest-confidence validated items come
    first
  * returns aggregate counts so the UI can show bars/badges ("23 comptes, 3
    validés")
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (kept for type hints if needed)

from src.db.types import DataType, VerificationStatus
from src.deps import CurrentUser, DbSession
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation
from src.models.user import User

router = APIRouter(tags=["identity"])


class DatapointSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: DataType
    value: str
    status: VerificationStatus
    confidence: float | None
    source_url: str | None
    source_connector_id: uuid.UUID | None
    notes: str | None
    extracted_at: datetime | None
    created_at: datetime


class TypeGroup(BaseModel):
    data_type: DataType
    total: int
    validated: int
    rejected: int
    items: list[DatapointSummary]


class IdentityCard(BaseModel):
    investigation_id: uuid.UUID
    entity_id: uuid.UUID
    display_name: str
    groups: list[TypeGroup]
    totals: dict[str, int]   # {"total": 42, "validated": 8, "unverified": 32, "rejected": 2}


@router.get(
    "/investigations/{investigation_id}/identity",
    response_model=IdentityCard,
)
async def get_identity(
    investigation_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> IdentityCard:
    inv = await db.get(Investigation, investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Load the primary entity (role=target, earliest created)
    ent_stmt = (
        select(Entity)
        .where(Entity.investigation_id == investigation_id)
        .order_by(Entity.created_at)
        .limit(1)
    )
    entity = (await db.execute(ent_stmt)).scalar_one_or_none()
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation has no entity yet",
        )

    dp_stmt = (
        select(DataPoint)
        .where(DataPoint.entity_id == entity.id)
        .order_by(DataPoint.type, DataPoint.status, DataPoint.created_at)
    )
    datapoints = list((await db.execute(dp_stmt)).scalars().all())

    # Group by type, sort within group by (validated first, highest confidence)
    by_type: dict[DataType, list[DataPoint]] = defaultdict(list)
    for dp in datapoints:
        by_type[dp.type].append(dp)

    # Declare the display order — the fiche should feel coherent, not random.
    PREFERRED_ORDER = [
        DataType.NAME, DataType.DATE_OF_BIRTH, DataType.PHOTO,
        DataType.EMAIL, DataType.PHONE,
        DataType.USERNAME, DataType.ACCOUNT, DataType.URL,
        DataType.ADDRESS, DataType.LOCATION,
        DataType.EMPLOYER, DataType.SCHOOL, DataType.FAMILY,
        DataType.DOMAIN, DataType.IP,
        DataType.OTHER,
    ]

    def _status_order(s: VerificationStatus) -> int:
        # validated first, then unverified, then rejected
        return {
            VerificationStatus.VALIDATED: 0,
            VerificationStatus.UNVERIFIED: 1,
            VerificationStatus.REJECTED: 2,
        }[s]

    groups: list[TypeGroup] = []
    for dtype in PREFERRED_ORDER:
        rows = by_type.get(dtype, [])
        if not rows:
            continue
        rows.sort(key=lambda d: (_status_order(d.status), -(d.confidence or 0)))
        validated = sum(1 for d in rows if d.status == VerificationStatus.VALIDATED)
        rejected = sum(1 for d in rows if d.status == VerificationStatus.REJECTED)
        groups.append(
            TypeGroup(
                data_type=dtype,
                total=len(rows),
                validated=validated,
                rejected=rejected,
                items=[DatapointSummary.model_validate(d) for d in rows],
            )
        )

    totals = {
        "total": len(datapoints),
        "validated": sum(1 for d in datapoints if d.status == VerificationStatus.VALIDATED),
        "unverified": sum(1 for d in datapoints if d.status == VerificationStatus.UNVERIFIED),
        "rejected": sum(1 for d in datapoints if d.status == VerificationStatus.REJECTED),
    }

    return IdentityCard(
        investigation_id=investigation_id,
        entity_id=entity.id,
        display_name=entity.display_name,
        groups=groups,
        totals=totals,
    )
