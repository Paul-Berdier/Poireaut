"""DataPoint — an atomic fact attached to an Entity.

Each DataPoint carries:
  * a typed value (email, username, photo URL, …)
  * a verification status (the investigator validates or rejects it)
  * a provenance: produced by a Connector, pivoting from another DataPoint.

The self-referential `source_datapoint_id` is what lets us draw the spider web:
an edge goes from the source DataPoint → this DataPoint, labelled with the
Connector that discovered it.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.db.types import DataType, VerificationStatus

if TYPE_CHECKING:
    from src.models.connector import Connector
    from src.models.entity import Entity
    from src.models.user import User


class DataPoint(Base):
    __tablename__ = "datapoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type: Mapped[DataType] = mapped_column(
        Enum(DataType, name="data_type"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        default=VerificationStatus.UNVERIFIED,
        nullable=False,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ─── Provenance ────────────────────────────────────────────────
    # Null if the investigator typed it in manually.
    source_connector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Null for the seed datapoint of an investigation; otherwise points at the
    # datapoint that was fed into the connector to produce this one.
    source_datapoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datapoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ─── Validation audit ──────────────────────────────────────────
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # ─── Relationships ─────────────────────────────────────────────
    entity: Mapped["Entity"] = relationship(
        back_populates="datapoints",
        foreign_keys=[entity_id],
    )
    source_connector: Mapped["Connector | None"] = relationship(
        foreign_keys=[source_connector_id],
    )
    source_datapoint: Mapped["DataPoint | None"] = relationship(
        remote_side="DataPoint.id",
        foreign_keys=[source_datapoint_id],
    )
    validator: Mapped["User | None"] = relationship(foreign_keys=[validated_by])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DataPoint {self.type.value}={self.value!r} {self.status.value}>"
