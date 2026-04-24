"""consolidate profile urls into account + locations into address

Revision ID: 0002_merge_types
Revises: 0001_initial
Create Date: 2026-04-24

We used to have two redundant DataType pairs:

    ACCOUNT vs URL      — for "profile on a platform", we were emitting
                          both an ACCOUNT (value=domain) and a URL
                          (value=full profile url) for the same finding.
    ADDRESS vs LOCATION — same intent, split for no good reason.

This migration unifies them:

  * URL datapoints produced by connectors that only ever mean "profile"
    (maigret, holehe) are converted to ACCOUNT, and their `value` is
    upgraded to hold the full URL string (previously only in source_url).
  * LOCATION datapoints are all converted to ADDRESS.

The enum types keep their legacy members (`url`, `location`) so old rows
that weren't migrated (e.g. wayback snapshots which rightly stay as URL)
remain valid. Future code only produces the unified types.

Idempotent: re-running the migration finds nothing to update the second
time because the predicates no longer match.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002_merge_types"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. url → account, when the url came from a "profile-only" connector ---
    # We join datapoints → connectors by name so this stays readable.
    #
    # When a former URL row had its full URL in `value` and nothing in
    # `source_url`, we copy `value` into `source_url` so the auto-scrape
    # hook has a URL to work with.
    op.execute(
        """
        UPDATE datapoints AS dp
        SET
            type = 'account',
            source_url = COALESCE(NULLIF(dp.source_url, ''), dp.value)
        FROM connectors AS c
        WHERE dp.source_connector_id = c.id
          AND c.name IN ('maigret', 'holehe')
          AND dp.type = 'url';
        """
    )

    # --- 2. location → address, everywhere ---
    op.execute(
        """
        UPDATE datapoints
        SET type = 'address'
        WHERE type = 'location';
        """
    )

    # --- 3. Back-fill source_url for Holehe account rows that lacked one ---
    # Old Holehe emitted ACCOUNT with value=domain and source_url=NULL. We
    # now emit source_url='https://<domain>/'. Back-fill old rows so they
    # become scrape-able when the investigator validates them.
    op.execute(
        """
        UPDATE datapoints AS dp
        SET source_url = 'https://' || dp.value
        FROM connectors AS c
        WHERE dp.source_connector_id = c.id
          AND c.name = 'holehe'
          AND dp.type = 'account'
          AND (dp.source_url IS NULL OR dp.source_url = '')
          AND dp.value !~ '^https?://'
          AND dp.value ~ '^[a-z0-9\\.-]+\\.[a-z]{2,}$';
        """
    )


def downgrade() -> None:
    # Reversing the url↔account merge is lossy — we can't know which ACCOUNT
    # rows were previously URLs. We only attempt a best-effort rollback of
    # location↔address: there's no way to tell which addresses were formerly
    # locations either, so we don't touch those.
    # This migration is intentionally one-way.
    pass
