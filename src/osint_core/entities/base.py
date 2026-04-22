"""Core entity primitives.

An OSINT investigation is a *graph* where:
  - nodes = Entity instances (Username, Email, Account, Person, ...)
  - edges = Relationship instances (found_on, owns, co_located, ...)

Every piece of information carries Evidence: we never store a fact without
its provenance. That's what distinguishes an OSINT tool from a scraper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Confidence(float, Enum):
    """Discrete confidence levels. Stored as float so arithmetic still works."""

    LOW = 0.3
    MEDIUM = 0.6
    HIGH = 0.85
    CONFIRMED = 1.0


class Evidence(BaseModel):
    """Provenance record for a piece of information.

    Every Entity and Relationship carries a list of Evidence records.
    When the same fact is confirmed by multiple collectors, we stack
    evidence; confidence becomes the max across all evidence.
    """

    model_config = ConfigDict(frozen=False)

    collector: str = Field(description="Name of the collector that produced this")
    collected_at: datetime = Field(default_factory=_utcnow)
    source_url: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=Confidence.MEDIUM.value, ge=0.0, le=1.0)
    notes: str | None = None


class Entity(BaseModel):
    """Abstract base class for all investigation entities.

    Subclasses override `entity_type` as a Literal[...] so Pydantic can use it
    as a discriminator when serializing/deserializing heterogeneous graphs.
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    entity_type: str = "entity"  # overridden in subclasses
    value: str = Field(description="Canonical string representation")
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime = Field(default_factory=_utcnow)
    last_seen: datetime = Field(default_factory=_utcnow)

    @property
    def confidence(self) -> float:
        """Aggregate confidence = max across evidence records."""
        if not self.evidence:
            return 0.0
        return max(e.confidence for e in self.evidence)

    def dedup_key(self) -> str:
        """Key used to identify that two entities refer to the same real-world thing.

        Two entities with the same dedup_key should be merged, not duplicated.
        """
        return f"{self.entity_type}:{self.value.lower()}"

    # Fields protected from "fill-the-gaps" merge logic
    _MERGE_PROTECTED: frozenset[str] = frozenset(
        {"id", "entity_type", "value", "evidence", "metadata", "first_seen", "last_seen"}
    )

    def merge(self, other: Entity) -> Entity:
        """Merge another entity of the same dedup_key into this one.

        Rules:
          * Evidence lists are concatenated (provenance is cumulative).
          * Metadata dicts are updated (other wins on conflict).
          * None-valued fields on self are filled in from other ("upgrade").
            Non-None fields are never overwritten to prevent low-confidence
            data from clobbering earlier findings.
          * Timestamps widen to the broadest observed range.
        """
        if self.dedup_key() != other.dedup_key():
            raise ValueError(
                f"Cannot merge distinct entities: {self.dedup_key()} vs {other.dedup_key()}"
            )
        self.evidence.extend(other.evidence)
        self.metadata.update(other.metadata)
        for field_name in type(self).model_fields:
            if field_name in self._MERGE_PROTECTED:
                continue
            current = getattr(self, field_name, None)
            new_value = getattr(other, field_name, None)
            if current is None and new_value is not None:
                setattr(self, field_name, new_value)
        self.first_seen = min(self.first_seen, other.first_seen)
        self.last_seen = max(self.last_seen, other.last_seen)
        return self

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(value={self.value!r}, conf={self.confidence:.2f})"
