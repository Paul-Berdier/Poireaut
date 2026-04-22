"""Event types that flow through the bus."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from osint_core.entities.base import Entity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EntityDiscovered(BaseModel):
    """A collector found (or confirmed) an entity.

    `origin_entity_id` lets us reconstruct the causal chain:
    "I found this Account because I was investigating that Username."
    This is what lets the correlation engine later draw the graph edges.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    entity: Entity
    origin_collector: str
    origin_entity_id: UUID | None = None
    timestamp: datetime = Field(default_factory=_utcnow)
