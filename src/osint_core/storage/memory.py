"""In-memory graph store — entities + relationships.

Simple and fast for CLI investigations up to ~10k entities. Swap in Neo4j
later for persistent / cross-session investigations.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from osint_core.bus.events import EntityDiscovered
from osint_core.entities.base import Entity, Evidence
from osint_core.entities.graph import Relationship


class InMemoryGraphStore:
    def __init__(self) -> None:
        self._by_key: dict[str, Entity] = {}
        self._by_id: dict[UUID, Entity] = {}
        self._relationships: list[Relationship] = []
        # Fast dedup of edges by (source, target, predicate)
        self._edge_keys: set[tuple[UUID, UUID, str]] = set()

    # --- Entities ----------------------------------------------------------

    def add_entity(self, entity: Entity) -> Entity:
        """Idempotent upsert: merges into existing if dedup_key matches."""
        key = entity.dedup_key()
        if key in self._by_key:
            return self._by_key[key].merge(entity)
        self._by_key[key] = entity
        self._by_id[entity.id] = entity
        return entity

    def add_event(self, event: EntityDiscovered) -> Entity:
        """Upsert entity and auto-create a 'derived_from' edge to its origin.

        This is the primary write path for the investigation graph: each
        published event both contributes to the entity store and weaves a
        causal thread back to whatever parent entity triggered its discovery.
        A seed (no origin_entity_id) creates a node without any edge.
        """
        entity = self.add_entity(event.entity)
        origin_id = event.origin_entity_id
        if origin_id is not None and origin_id != entity.id:
            edge_key = (origin_id, entity.id, "derived_from")
            if edge_key not in self._edge_keys:
                self._edge_keys.add(edge_key)
                self._relationships.append(
                    Relationship(
                        source_id=origin_id,
                        target_id=entity.id,
                        predicate="derived_from",
                        evidence=[
                            Evidence(
                                collector=event.origin_collector,
                                collected_at=event.timestamp,
                                confidence=0.9,
                                notes=f"Discovered via {event.origin_collector}",
                            )
                        ],
                    )
                )
        return entity

    def get(self, entity_id: UUID) -> Entity | None:
        return self._by_id.get(entity_id)

    def by_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self._by_key.values() if e.entity_type == entity_type]

    def all(self) -> Iterable[Entity]:
        return self._by_key.values()

    # --- Relationships -----------------------------------------------------

    def add_relationship(self, rel: Relationship) -> Relationship:
        """Idempotent upsert: a repeat (source, target, predicate) triple
        merges its evidence into the existing edge rather than duplicating."""
        key = (rel.source_id, rel.target_id, rel.predicate)
        if key in self._edge_keys:
            for existing in self._relationships:
                if (
                    existing.source_id,
                    existing.target_id,
                    existing.predicate,
                ) == key:
                    existing.evidence.extend(rel.evidence)
                    existing.metadata.update(rel.metadata)
                    return existing
        self._edge_keys.add(key)
        self._relationships.append(rel)
        return rel

    def relationships_of(self, entity_id: UUID) -> list[Relationship]:
        return [
            r
            for r in self._relationships
            if r.source_id == entity_id or r.target_id == entity_id
        ]

    @property
    def relationships(self) -> list[Relationship]:
        return list(self._relationships)

    # --- Meta --------------------------------------------------------------

    def summary(self) -> dict[str, int]:
        counter: Counter[str] = Counter(e.entity_type for e in self._by_key.values())
        return dict(counter) | {"relationships": len(self._relationships)}

    def __len__(self) -> int:
        return len(self._by_key)
