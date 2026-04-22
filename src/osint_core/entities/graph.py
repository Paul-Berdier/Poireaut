"""Typed relationships between entities — the edges of the investigation graph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from osint_core.entities.base import Evidence


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Canonical predicate vocabulary. Keep it small and meaningful; extend with care.
# Using a fixed list (rather than arbitrary strings) lets us write correlation
# rules and graph queries reliably.
PREDICATES = frozenset({
    "found_on",         # Username --found_on--> Account
    "owns",             # Person --owns--> Account
    "has_email",        # Person --has_email--> Email
    "has_phone",        # Person --has_phone--> Phone
    "registered_domain",  # Person --registered_domain--> Domain
    "posted_from",      # Account --posted_from--> Location
    "located_at",       # ImageAsset --located_at--> Location
    "same_avatar_as",   # Account --same_avatar_as--> Account
    "same_bio_as",      # Account --same_bio_as--> Account
    "co_occurs_with",   # generic co-mention
    "derived_from",     # Entity derived from another (e.g. email from account bio)
})


class Relationship(BaseModel):
    """A typed, evidenced edge between two entities."""

    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    target_id: UUID
    predicate: str
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)

    def __repr__(self) -> str:
        return f"({self.source_id} --{self.predicate}--> {self.target_id})"
