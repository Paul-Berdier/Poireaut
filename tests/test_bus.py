"""Tests for the async event bus."""

import asyncio

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.entities.identifiers import Username


async def _make_event(value: str, source: str = "test") -> EntityDiscovered:
    return EntityDiscovered(
        entity=Username(value=value),
        origin_collector=source,
    )


@pytest.mark.asyncio
async def test_subscribe_and_publish_invokes_handler() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: EntityDiscovered) -> None:
        received.append(event.entity.value)

    bus.subscribe("username", handler)
    await bus.publish(await _make_event("alice"))
    await bus.drain()

    assert received == ["alice"]


@pytest.mark.asyncio
async def test_dedup_prevents_double_dispatch() -> None:
    bus = EventBus()
    count = 0

    async def handler(event: EntityDiscovered) -> None:
        nonlocal count
        count += 1

    bus.subscribe("username", handler)  # dedup=True by default
    await bus.publish(await _make_event("alice"))
    await bus.publish(await _make_event("alice"))  # same dedup_key
    await bus.publish(await _make_event("ALICE"))  # same dedup_key (lowercased)
    await bus.drain()

    assert count == 1


@pytest.mark.asyncio
async def test_dedup_false_receives_every_publish() -> None:
    """Observers (e.g. storage) subscribe with dedup=False to see every event."""
    bus = EventBus()
    observer_calls = 0
    collector_calls = 0

    async def observer(event: EntityDiscovered) -> None:
        nonlocal observer_calls
        observer_calls += 1

    async def collector(event: EntityDiscovered) -> None:
        nonlocal collector_calls
        collector_calls += 1

    bus.subscribe("username", observer, dedup=False)
    bus.subscribe("username", collector)  # dedup=True
    for _ in range(3):
        await bus.publish(await _make_event("alice"))
    await bus.drain()

    assert observer_calls == 3, "observer must see every publish"
    assert collector_calls == 1, "collector must dedup"


@pytest.mark.asyncio
async def test_multiple_handlers_run_concurrently() -> None:
    bus = EventBus()
    order: list[str] = []

    async def slow(event: EntityDiscovered) -> None:
        await asyncio.sleep(0.05)
        order.append("slow")

    async def fast(event: EntityDiscovered) -> None:
        order.append("fast")

    bus.subscribe("username", slow)
    bus.subscribe("username", fast)
    await bus.publish(await _make_event("alice"))
    await bus.drain()

    # fast should finish before slow despite being registered second
    assert order == ["fast", "slow"]


@pytest.mark.asyncio
async def test_handler_exceptions_are_isolated() -> None:
    bus = EventBus()
    survived = False

    async def broken(event: EntityDiscovered) -> None:
        raise RuntimeError("boom")

    async def ok(event: EntityDiscovered) -> None:
        nonlocal survived
        survived = True

    bus.subscribe("username", broken)
    bus.subscribe("username", ok)
    await bus.publish(await _make_event("alice"))
    await bus.drain()

    assert survived, "healthy handler must run even if another crashed"


@pytest.mark.asyncio
async def test_drain_waits_for_cascaded_publishes() -> None:
    """A handler that itself publishes new events should be awaited too."""
    bus = EventBus()
    seen: list[str] = []

    async def primary(event: EntityDiscovered) -> None:
        seen.append(event.entity.value)
        # Cascade: publish a new entity
        if event.entity.value == "root":
            await bus.publish(
                EntityDiscovered(
                    entity=Username(value="leaf"),
                    origin_collector="cascade",
                )
            )

    bus.subscribe("username", primary)
    await bus.publish(await _make_event("root"))
    await bus.drain()

    assert sorted(seen) == ["leaf", "root"]
