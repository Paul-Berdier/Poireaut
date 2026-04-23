"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-23

Creates all Poireaut tables:
  users → investigations → entities → datapoints
  connectors → connector_runs
plus their PostgreSQL enum types.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─── Enum type definitions ─────────────────────────────────────
_user_role = postgresql.ENUM(
    "admin", "investigator", name="user_role", create_type=False
)
_investigation_status = postgresql.ENUM(
    "active", "closed", "archived", name="investigation_status", create_type=False
)
_entity_role = postgresql.ENUM(
    "target", "related", name="entity_role", create_type=False
)
_data_type = postgresql.ENUM(
    "email", "username", "phone", "name", "address", "url", "photo",
    "ip", "domain", "date_of_birth", "account", "location",
    "employer", "school", "family", "other",
    name="data_type", create_type=False,
)
_verification_status = postgresql.ENUM(
    "unverified", "validated", "rejected",
    name="verification_status", create_type=False,
)
_connector_category = postgresql.ENUM(
    "email", "username", "phone", "image", "domain", "ip", "breach",
    "people", "company", "socmint", "geoint", "archive", "other",
    name="connector_category", create_type=False,
)
_connector_cost = postgresql.ENUM(
    "free", "api_key_free_tier", "paid", name="connector_cost", create_type=False
)
_health_status = postgresql.ENUM(
    "ok", "degraded", "dead", "unknown", name="health_status", create_type=False
)
_run_status = postgresql.ENUM(
    "pending", "running", "success", "failed", "timeout",
    name="run_status", create_type=False,
)

_ALL_ENUMS = (
    _user_role, _investigation_status, _entity_role, _data_type,
    _verification_status, _connector_category, _connector_cost,
    _health_status, _run_status,
)


def upgrade() -> None:
    bind = op.get_bind()

    # Create all enum types first
    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ─── users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", _user_role, nullable=False, server_default="investigator"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ─── investigations ───────────────────────────────────────
    op.create_table(
        "investigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", _investigation_status,
            nullable=False, server_default="active",
        ),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_investigations_owner_id_users"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_investigations_owner_id", "investigations", ["owner_id"])
    op.create_index("ix_investigations_status", "investigations", ["status"])

    # ─── entities ─────────────────────────────────────────────
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "investigation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "investigations.id", ondelete="CASCADE",
                name="fk_entities_investigation_id_investigations",
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", _entity_role, nullable=False, server_default="target"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_entities_investigation_id", "entities", ["investigation_id"])

    # ─── connectors ───────────────────────────────────────────
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("category", _connector_category, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("homepage_url", sa.String(512), nullable=True),
        sa.Column(
            "input_types", postgresql.ARRAY(_data_type),
            nullable=False, server_default="{}",
        ),
        sa.Column(
            "output_types", postgresql.ARRAY(_data_type),
            nullable=False, server_default="{}",
        ),
        sa.Column("cost", _connector_cost, nullable=False, server_default="free"),
        sa.Column("health", _health_status, nullable=False, server_default="unknown"),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_connectors_name"),
    )
    op.create_index("ix_connectors_category", "connectors", ["category"])

    # ─── datapoints ───────────────────────────────────────────
    op.create_table(
        "datapoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "entities.id", ondelete="CASCADE",
                name="fk_datapoints_entity_id_entities",
            ),
            nullable=False,
        ),
        sa.Column("type", _data_type, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "status", _verification_status,
            nullable=False, server_default="unverified",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),

        sa.Column(
            "source_connector_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "connectors.id", ondelete="SET NULL",
                name="fk_datapoints_source_connector_id_connectors",
            ),
            nullable=True,
        ),
        sa.Column(
            "source_datapoint_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "datapoints.id", ondelete="SET NULL",
                name="fk_datapoints_source_datapoint_id_datapoints",
            ),
            nullable=True,
        ),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "validated_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL",
                name="fk_datapoints_validated_by_users",
            ),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_datapoints_entity_id", "datapoints", ["entity_id"])
    op.create_index("ix_datapoints_type", "datapoints", ["type"])
    op.create_index("ix_datapoints_status", "datapoints", ["status"])
    op.create_index("ix_datapoints_source_connector_id", "datapoints", ["source_connector_id"])
    op.create_index("ix_datapoints_source_datapoint_id", "datapoints", ["source_datapoint_id"])

    # ─── connector_runs ───────────────────────────────────────
    op.create_table(
        "connector_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connector_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "connectors.id", ondelete="CASCADE",
                name="fk_connector_runs_connector_id_connectors",
            ),
            nullable=False,
        ),
        sa.Column(
            "input_datapoint_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "datapoints.id", ondelete="SET NULL",
                name="fk_connector_runs_input_datapoint_id_datapoints",
            ),
            nullable=True,
        ),
        sa.Column("status", _run_status, nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_output", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_connector_runs_connector_id", "connector_runs", ["connector_id"])
    op.create_index("ix_connector_runs_input_datapoint_id", "connector_runs", ["input_datapoint_id"])
    op.create_index("ix_connector_runs_status", "connector_runs", ["status"])


def downgrade() -> None:
    op.drop_table("connector_runs")
    op.drop_table("datapoints")
    op.drop_table("connectors")
    op.drop_table("entities")
    op.drop_table("investigations")
    op.drop_table("users")

    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
