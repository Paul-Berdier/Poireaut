"""MaigretSiteHealth — DB-backed health status for Maigret's bundled sites.

Maigret bundles ~2500 sites, but a large fraction is dead, returns false
positives, or blocks crawlers. We don't want to filter only by TLD —
some .com sites are dead, and some .ru sites might be alive and useful.

A daily Celery beat task probes each enabled Maigret site against a
known-impossible username (a long random string), measures HTTP status
and content, and flags the site:

  - `dead`: the request fails (timeout, DNS, connection refused)
  - `blocking`: returns 403 / 999 (likely Cloudflare / bot block)
  - `false_positive`: returns HTTP 200 + content matches "user found"
    pattern when probed with a guaranteed-nonexistent username
  - `ok`: behaves correctly (404 / specific not-found content)

The maigret connector reads this table at runtime and passes the
flagged sites as `disabled_sites_set` to Maigret's search call.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class MaigretSiteHealth(Base):
    """One row per Maigret site we've ever probed. Updated daily."""
    __tablename__ = "maigret_site_health"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Maigret's canonical site name from its data.json (e.g. "GitHub", "Twitter").
    # Unique — one row per site.
    site_name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True,
    )

    # Status from the latest probe:
    #   ok / dead / blocking / false_positive / unknown
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    # True if Maigret should skip this site (status != "ok").
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Last probe details
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Rolling counts for trend tracking
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MaigretSiteHealth {self.site_name} {self.status}>"
