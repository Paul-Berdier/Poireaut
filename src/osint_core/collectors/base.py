"""Base class for all collectors.

A collector is a plugin that:
  1. Listens for entities of specific types (via `consumes`)
  2. Performs I/O (HTTP calls, lib invocations, file reads)
  3. Emits new entities back onto the bus (of types in `produces`)
  4. Optionally emits semantic relationships to a RelationshipSink

The base class handles registration and helper methods; subclasses only
need to implement `collect()`.

Dedup semantics
---------------
By default, a collector sees each unique entity (by dedup_key) at most
once — the bus remembers that (collector, entity) pair. Collectors that
need to react to *updates* of an already-seen entity (e.g. AvatarHash
reacts when enrichment adds `avatar_url` to an Account that was already
published bare) can opt out by setting `dedup = False` on their class.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar, Protocol, runtime_checkable

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.entities.base import Entity
from osint_core.entities.graph import Relationship

log = logging.getLogger(__name__)


@runtime_checkable
class RelationshipSink(Protocol):
    """Anything that can accept a Relationship (typically the graph store)."""

    def add_relationship(self, rel: Relationship) -> None: ...


class BaseCollector(ABC):
    """Abstract collector.

    Subclass contract:
      - set `name`, `consumes`, `produces` as class attributes
      - implement `collect(event)`: extract data, call `self.emit(entity, event)`
      - optionally override `dedup = False` to see every publish (including
        updates to already-seen entities)
    """

    name: ClassVar[str] = "unnamed"
    consumes: ClassVar[list[str]] = []
    produces: ClassVar[list[str]] = []
    # Default: the bus will dispatch at most once per unique entity to this
    # collector. Set to False if you need to react to upgrades/re-emits.
    dedup: ClassVar[bool] = True

    def __init__(
        self,
        bus: EventBus,
        relationship_sink: RelationshipSink | None = None,
    ) -> None:
        self.bus = bus
        self.relationship_sink = relationship_sink
        self.log = logging.getLogger(f"collector.{self.name}")

    def register(self) -> None:
        """Subscribe this collector to all types it consumes."""
        for entity_type in self.consumes:
            self.bus.subscribe(entity_type, self._handle, dedup=self.dedup)

    async def _handle(self, event: EntityDiscovered) -> None:
        """Internal entry point — wraps collect() with timing."""
        import time

        start = time.monotonic()
        try:
            await self.collect(event)
        finally:
            elapsed = time.monotonic() - start
            self.log.debug(
                "%s processed %s in %.2fs", self.name, event.entity.dedup_key(), elapsed
            )

    @abstractmethod
    async def collect(self, event: EntityDiscovered) -> None:
        """Do the work: extract info from `event.entity` and emit findings."""

    async def emit(self, entity: Entity, origin_event: EntityDiscovered) -> None:
        """Helper: publish a newly discovered entity with proper provenance."""
        await self.bus.publish(
            EntityDiscovered(
                entity=entity,
                origin_collector=self.name,
                origin_entity_id=origin_event.entity.id,
            )
        )

    def emit_relationship(self, relationship: Relationship) -> None:
        """Helper: publish a semantic relationship to the configured sink.

        Relationships don't flow through the bus (they're edges, not nodes),
        so they go straight to whatever sink was wired at init-time — the
        graph store in normal use, a mock in tests.
        """
        if self.relationship_sink is None:
            self.log.debug(
                "emit_relationship called but no sink is configured; dropping %s",
                relationship.predicate,
            )
            return
        self.relationship_sink.add_relationship(relationship)
