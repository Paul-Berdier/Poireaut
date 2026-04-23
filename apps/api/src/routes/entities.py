"""Entity routes + graph projection for the spider web.

Routes:
  POST   /investigations/{id}/entities        → create entity
  GET    /investigations/{id}/entities        → list entities of investigation
  GET    /investigations/{id}/graph           → nodes + edges for the UI

  GET    /entities/{id}                       → single entity
  PATCH  /entities/{id}                       → update
  DELETE /entities/{id}                       → delete
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.deps import CurrentUser, DbSession
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation
from src.models.user import User
from src.schemas.datapoint import GraphEdge, GraphNode, GraphOut
from src.schemas.entity import EntityCreate, EntityOut, EntityUpdate

router = APIRouter(tags=["entities"])


# ─── Helpers ──────────────────────────────────────────────────

async def _get_owned_investigation(
    db: AsyncSession, investigation_id: uuid.UUID, user: User
) -> Investigation:
    inv = await db.get(Investigation, investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return inv


async def _get_owned_entity(
    db: AsyncSession, entity_id: uuid.UUID, user: User
) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    inv = await db.get(Investigation, entity.investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return entity


# ─── Nested under investigations ──────────────────────────────

@router.get(
    "/investigations/{investigation_id}/entities",
    response_model=list[EntityOut],
)
async def list_entities(
    investigation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[Entity]:
    await _get_owned_investigation(db, investigation_id, user)
    stmt = (
        select(Entity)
        .where(Entity.investigation_id == investigation_id)
        .order_by(Entity.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/investigations/{investigation_id}/entities",
    response_model=EntityOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity(
    investigation_id: uuid.UUID,
    payload: EntityCreate,
    user: CurrentUser,
    db: DbSession,
) -> Entity:
    await _get_owned_investigation(db, investigation_id, user)
    entity = Entity(
        investigation_id=investigation_id,
        display_name=payload.display_name,
        role=payload.role,
        notes=payload.notes,
    )
    db.add(entity)
    await db.flush()
    await db.refresh(entity)
    return entity


@router.get(
    "/investigations/{investigation_id}/graph",
    response_model=GraphOut,
)
async def get_graph(
    investigation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> GraphOut:
    """Return the full graph of an investigation: entities + datapoints + pivots."""
    await _get_owned_investigation(db, investigation_id, user)

    entities_stmt = (
        select(Entity)
        .where(Entity.investigation_id == investigation_id)
        .options(selectinload(Entity.datapoints).selectinload(DataPoint.source_connector))
    )
    entities = list((await db.execute(entities_stmt)).scalars().all())

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for entity in entities:
        nodes.append(
            GraphNode(id=entity.id, kind="entity", label=entity.display_name)
        )
        for dp in entity.datapoints:
            nodes.append(
                GraphNode(
                    id=dp.id,
                    kind="datapoint",
                    label=dp.value,
                    data_type=dp.type,
                    status=dp.status,
                    confidence=dp.confidence,
                )
            )
            # Entity → datapoint (ownership link)
            edges.append(
                GraphEdge(
                    id=f"own-{entity.id}-{dp.id}",
                    source=entity.id,
                    target=dp.id,
                    kind="owns",
                )
            )
            # Pivot edge from source datapoint → this one
            if dp.source_datapoint_id is not None:
                edges.append(
                    GraphEdge(
                        id=f"pv-{dp.source_datapoint_id}-{dp.id}",
                        source=dp.source_datapoint_id,
                        target=dp.id,
                        kind="pivot",
                        connector_name=(
                            dp.source_connector.name
                            if dp.source_connector is not None
                            else None
                        ),
                    )
                )

    return GraphOut(investigation_id=investigation_id, nodes=nodes, edges=edges)


# ─── Flat entity endpoints ────────────────────────────────────

@router.get("/entities/{entity_id}", response_model=EntityOut)
async def get_entity(
    entity_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Entity:
    return await _get_owned_entity(db, entity_id, user)


@router.patch("/entities/{entity_id}", response_model=EntityOut)
async def update_entity(
    entity_id: uuid.UUID,
    payload: EntityUpdate,
    user: CurrentUser,
    db: DbSession,
) -> Entity:
    entity = await _get_owned_entity(db, entity_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    await db.flush()
    await db.refresh(entity)
    return entity


@router.delete(
    "/entities/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_entity(
    entity_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    entity = await _get_owned_entity(db, entity_id, user)
    await db.delete(entity)
