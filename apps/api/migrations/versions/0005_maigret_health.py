"""maigret_site_health table

Revision ID: 0005_maigret_health
Revises: 0004_api_keys
Create Date: 2026-05-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_maigret_health"
down_revision: Union[str, None] = "0004_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "maigret_site_health",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
        ),
        sa.Column("site_name", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "status", sa.String(32), nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "is_disabled", sa.Boolean, nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer, nullable=True),
        sa.Column("last_error", sa.String(512), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer, nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "consecutive_successes", sa.Integer, nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_maigret_site_health_is_disabled",
        "maigret_site_health", ["is_disabled"],
    )
    op.create_index(
        "ix_maigret_site_health_site_name",
        "maigret_site_health", ["site_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_maigret_site_health_site_name", table_name="maigret_site_health",
    )
    op.drop_index(
        "ix_maigret_site_health_is_disabled", table_name="maigret_site_health",
    )
    op.drop_table("maigret_site_health")
