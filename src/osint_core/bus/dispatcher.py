"""Async pub/sub dispatcher.

This is the heart of the orchestration: collectors subscribe to entity
types they can enrich, and publish new entities they discover. The bus
deduplicates, dispatches handlers concurrently, and drains at the end.

Design notes:
  * Deduplication happens at publish time using `Entity.dedup_key()`.
    An entity discovered twice (by different collectors) is only dispatched
    once, but its evidence is merged in the storage layer.
  * Handler errors are caught and logged — one broken collector never
    crashes the investigation.
  * `drain()` awaits all in-flight tasks to support "fan-out then wait"
    workflows (CLI, scripts). For long-running daemons, use publish without
    drain and keep the loop alive.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from osint_core.bus.events import EntityDiscovered

log = logging.getLogger(__name__)

Handler = Callable[[EntityDiscovered], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[Handler, bool]]] = defaultdict(list)
        # Per-handler dedup: {(id(handler), dedup_key)} already dispatched
        self._dispatched: set[tuple[int, str]] = set()
        self._tasks: set[asyncio.Task] = set()

    def subscribe(
        self, entity_type: str, handler: Handler, *, dedup: bool = True
    ) -> None:
        """Subscribe a handler to an entity type.

        Parameters
        ----------
        entity_type : str
            The entity type name (e.g. "username", "account").
        handler : async callable
            Invoked with an EntityDiscovered event.
        dedup : bool, default True
            If True, the handler is called at most once per unique dedup_key.
            Use False for observers that need to see every publish (e.g. the
            storage layer, which accumulates evidence across repeated findings).
        """
        self._handlers[entity_type].append((handler, dedup))
        log.debug(
            "subscribed %s to %s (dedup=%s)",
            getattr(handler, "__qualname__", handler),
            entity_type,
            dedup,
        )

    def subscribe_many(
        self, entity_types: list[str], handler: Handler, *, dedup: bool = True
    ) -> None:
        for t in entity_types:
            self.subscribe(t, handler, dedup=dedup)

    async def publish(self, event: EntityDiscovered) -> None:
        """Publish a discovered entity to all matching subscribers."""
        key = event.entity.dedup_key()
        handlers = self._handlers.get(event.entity.entity_type, [])
        dispatched_to = 0
        for handler, dedup in handlers:
            if dedup:
                hk = (id(handler), key)
                if hk in self._dispatched:
                    continue
                self._dispatched.add(hk)
            task = asyncio.create_task(self._safe_call(handler, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            dispatched_to += 1
        log.info(
            "publish %s [%s] -> %d/%d handlers",
            key,
            event.origin_collector,
            dispatched_to,
            len(handlers),
        )

    async def _safe_call(self, handler: Handler, event: EntityDiscovered) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception(
                "handler %s crashed on %s",
                getattr(handler, "__qualname__", handler),
                event.entity.dedup_key(),
            )

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for all in-flight (and cascaded) tasks to complete."""
        max_loops = 1000
        deadline_loop = 0
        while self._tasks and deadline_loop < max_loops:
            current = list(self._tasks)
            try:
                await asyncio.wait_for(
                    asyncio.gather(*current, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                log.warning("drain timeout — %d tasks still pending", len(self._tasks))
                break
            deadline_loop += 1

    @property
    def stats(self) -> dict[str, int]:
        return {
            "dispatched_pairs": len(self._dispatched),
            "in_flight_tasks": len(self._tasks),
            "subscriptions": sum(len(v) for v in self._handlers.values()),
        }
