"""auto-pivot columns + AutoPivotMode enum

Revision ID: 0003_autopivot
Revises: 0002_merge_types
Create Date: 2026-04-25

Adds:
  * New enum auto_pivot_mode ('off', 'manual_only', 'auto')
  * investigations.auto_pivot_mode + auto_pivot_min_confidence + auto_pivot_max_depth
  * datapoints.pivot_depth (default 0) + auto_pivoted_at + auto_pivot_blocked_reason

All new columns have safe defaults so existing rows keep working without
back-fill.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_autopivot"
down_revision: Union[str, None] = "0002_merge_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the auto_pivot_mode enum
    op.execute(
        "CREATE TYPE auto_pivot_mode AS ENUM ('off', 'manual_only', 'auto')"
    )

    # 2. Investigation settings columns
    op.add_column(
        "investigations",
        sa.Column(
            "auto_pivot_mode",
            sa.Enum("off", "manual_only", "auto",
                    name="auto_pivot_mode", create_type=False),
            server_default="auto",
            nullable=False,
        ),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "auto_pivot_min_confidence",
            sa.Float(),
            server_default="0.75",
            nullable=False,
        ),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "auto_pivot_max_depth",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )

    # 3. Datapoint provenance / depth columns
    op.add_column(
        "datapoints",
        sa.Column(
            "pivot_depth",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "datapoints",
        sa.Column(
            "auto_pivoted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "datapoints",
        sa.Column(
            "auto_pivot_blocked_reason",
            sa.String(length=255),
            nullable=True,
        ),
    )

    # 4. Helpful indexes for the orchestrator queries
    op.create_index(
        "ix_datapoints_pivot_depth",
        "datapoints",
        ["pivot_depth"],
    )
    op.create_index(
        "ix_datapoints_auto_pivoted_at",
        "datapoints",
        ["auto_pivoted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_datapoints_auto_pivoted_at", table_name="datapoints")
    op.drop_index("ix_datapoints_pivot_depth", table_name="datapoints")
    op.drop_column("datapoints", "auto_pivot_blocked_reason")
    op.drop_column("datapoints", "auto_pivoted_at")
    op.drop_column("datapoints", "pivot_depth")

    op.drop_column("investigations", "auto_pivot_max_depth")
    op.drop_column("investigations", "auto_pivot_min_confidence")
    op.drop_column("investigations", "auto_pivot_mode")

    op.execute("DROP TYPE auto_pivot_mode")
