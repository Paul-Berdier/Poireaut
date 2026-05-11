"""api_keys table

Revision ID: 0004_api_keys
Revises: 0003_autopivot
Create Date: 2026-05-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_api_keys"
down_revision: Union[str, None] = "0003_autopivot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("connector_name", sa.String(64), nullable=False),
        sa.Column("encrypted_value", sa.String(2048), nullable=False),
        sa.Column("masked_preview", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("user_id", "connector_name", name="uq_user_connector"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
