"""ApiKey — per-user encrypted credential for a connector.

We store one row per (user, connector_name). The actual key value is
encrypted at rest using Fernet (symmetric AES-128-CBC + HMAC). The
encryption key lives in env var POIREAUT_FERNET_KEY — without it the
storage layer refuses to read or write any key.

When the worker needs a key (e.g. Hunter.io), it calls
`get_api_key(user_id, "hunter")` which decrypts on the fly. The key
value is never serialized in API responses — only a masked preview
("sk-•••abc") is returned, derived from the plaintext for display.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.user import User


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        # One key per (user, connector) — newer overwrites older via UPSERT
        UniqueConstraint("user_id", "connector_name", name="uq_user_connector"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Free-form so any connector can have a key. Validated against the
    # connector registry at the route level — unknown names rejected.
    connector_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Encrypted blob. Always written via the encrypt helper, never raw.
    encrypted_value: Mapped[str] = mapped_column(String(2048), nullable=False)

    # Cached metadata to render the masked preview without decrypting on read.
    # Last 4 chars of the cleartext, with the prefix length so we can show
    # something like "sk-•••a1b2".
    masked_preview: Mapped[str] = mapped_column(String(32), nullable=False)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_test_ok: Mapped[bool | None] = mapped_column(default=None, nullable=True)

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ApiKey user={self.user_id} {self.connector_name}>"
