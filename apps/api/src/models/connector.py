"""Connector registry + per-invocation run log.

Every OSINT tool Poireaut can call is registered in the `connectors` table.
Each time the worker runs one, a ConnectorRun row records what happened:
inputs, status, duration, error, number of datapoints produced. This gives
a full audit trail and powers health monitoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
    RunStatus,
    pg_enum,
)


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    # Stable machine name — e.g. "holehe", "maigret", "crtsh".
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Pretty name for the UI.
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)

    category: Mapped[ConnectorCategory] = mapped_column(
        pg_enum(ConnectorCategory, name="connector_category"),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Which DataType can be fed in / comes out.
    input_types: Mapped[list[DataType]] = mapped_column(
        ARRAY(pg_enum(DataType, name="data_type")),
        nullable=False,
        default=list,
    )
    output_types: Mapped[list[DataType]] = mapped_column(
        ARRAY(pg_enum(DataType, name="data_type")),
        nullable=False,
        default=list,
    )

    cost: Mapped[ConnectorCost] = mapped_column(
        pg_enum(ConnectorCost, name="connector_cost"),
        default=ConnectorCost.FREE,
        nullable=False,
    )
    health: Mapped[HealthStatus] = mapped_column(
        pg_enum(HealthStatus, name="health_status"),
        default=HealthStatus.UNKNOWN,
        nullable=False,
    )
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    runs: Mapped[list["ConnectorRun"]] = relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Connector {self.name} {self.health.value}>"


class ConnectorRun(Base):
    __tablename__ = "connector_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The datapoint this run was invoked on (may be null for bulk/scheduled runs).
    input_datapoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datapoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[RunStatus] = mapped_column(
        pg_enum(RunStatus, name="run_status"),
        default=RunStatus.PENDING,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    connector: Mapped["Connector"] = relationship(back_populates="runs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConnectorRun {self.connector_id} {self.status.value}>"
