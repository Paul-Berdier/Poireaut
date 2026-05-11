"""Investigation — a case file owned by a User."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.db.types import AutoPivotMode, InvestigationStatus, pg_enum

if TYPE_CHECKING:
    from src.models.entity import Entity
    from src.models.user import User


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[InvestigationStatus] = mapped_column(
        pg_enum(InvestigationStatus, name="investigation_status"),
        default=InvestigationStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # ── Auto-pivot settings ────────────────────────────────
    # `auto_pivot_mode` decides whether new findings are pivoted on their own:
    #   - off:          never (user must click Pivoter)
    #   - manual_only:  only when the user validates a finding
    #   - auto:         every new finding above min_confidence triggers a pivot
    auto_pivot_mode: Mapped[AutoPivotMode] = mapped_column(
        pg_enum(AutoPivotMode, name="auto_pivot_mode"),
        default=AutoPivotMode.AUTO,    # ← aggressive by default per user spec
        nullable=False,
    )
    auto_pivot_min_confidence: Mapped[float] = mapped_column(
        Float, default=0.75, nullable=False,
    )
    auto_pivot_max_depth: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner: Mapped["User"] = relationship(back_populates="investigations")
    entities: Mapped[list["Entity"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Investigation {self.title!r}>"
