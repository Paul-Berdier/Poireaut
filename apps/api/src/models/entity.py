"""Entity — a person (or organisation) being investigated.

An investigation has at least one entity (the target). Pivots can surface
'related' entities (a sibling, an employer, an accomplice…) which get their
own entity record so their DataPoints stay grouped.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.db.types import EntityRole, pg_enum

if TYPE_CHECKING:
    from src.models.datapoint import DataPoint
    from src.models.investigation import Investigation


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[EntityRole] = mapped_column(
        pg_enum(EntityRole, name="entity_role"),
        default=EntityRole.TARGET,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    investigation: Mapped["Investigation"] = relationship(back_populates="entities")
    datapoints: Mapped[list["DataPoint"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
        foreign_keys="DataPoint.entity_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Entity {self.display_name!r} ({self.role.value})>"
