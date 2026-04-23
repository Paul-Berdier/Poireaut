"""Tests for WaybackCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.wayback import WaybackCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


def _account(profile_url: str = "https://github.com/alice") -> Account:
    return Account(
        value="github:alice",
        platform="github",
        username="alice",
        profile_url=profile_url,
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("account", "url"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    WaybackCollector(bus).register()
    return bus, store


async def _publish(bus: EventBus, store: InMemoryGraphStore, account: Account) -> None:
    store.add_entity(account)
    await bus.publish(EntityDiscovered(entity=account, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_snapshots_as_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    snapshots = [
        {"timestamp": "20150101000000", "original": "https://github.com/alice",
         "statuscode": "200", "mimetype": "text/html", "digest": "AAA"},
        {"timestamp": "20180601000000", "original": "https://github.com/alice",
         "statuscode": "200", "mimetype": "text/html", "digest": "BBB"},
        {"timestamp": "20230301000000", "original": "https://github.com/alice",
         "statuscode": "200", "mimetype": "text/html", "digest": "CCC"},
    ]

    async def fake_fetch(self, url: str) -> list[dict[str, Any]]:
        return snapshots

    monkeypatch.setattr(WaybackCollector, "_fetch_snapshots", fake_fetch)

    await _publish(bus, store, _account())

    urls = store.by_type("url")
    assert len(urls) == 3
    # All three should point at web.archive.org
    assert all("web.archive.org/web/" in u.value for u in urls)
    # Metadata preserves the archive-of relationship
    assert {u.metadata["archive_of"] for u in urls} == {"https://github.com/alice"}


@pytest.mark.asyncio
async def test_only_three_snapshots_kept_for_dense_histories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10 snapshots → only 3 (earliest, middle, latest) end up on the graph."""
    bus, store = await _wire()

    snapshots = [
        {
            "timestamp": f"2020{str(i+1).zfill(2)}01000000",
            "original": "https://github.com/alice",
            "statuscode": "200",
            "digest": f"D{i}",
        }
        for i in range(10)
    ]

    async def fake_fetch(self, url: str):
        return snapshots

    monkeypatch.setattr(WaybackCollector, "_fetch_snapshots", fake_fetch)
    await _publish(bus, store, _account())

    urls = store.by_type("url")
    assert len(urls) == 3
    timestamps = sorted(u.metadata["wayback_timestamp"] for u in urls)
    # Earliest + latest of the 10 input rows are represented.
    assert timestamps[0] == snapshots[0]["timestamp"]
    assert timestamps[-1] == snapshots[-1]["timestamp"]


@pytest.mark.asyncio
async def test_no_snapshots_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, url: str):
        return []

    monkeypatch.setattr(WaybackCollector, "_fetch_snapshots", fake_fetch)
    await _publish(bus, store, _account())

    assert store.by_type("url") == []


@pytest.mark.asyncio
async def test_account_without_profile_url_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    called = False

    async def fake_fetch(self, url: str):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(WaybackCollector, "_fetch_snapshots", fake_fetch)

    stub = Account(
        value="nowhere:alice",
        platform="nowhere",
        username="alice",
        profile_url=None,
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, stub)
    assert called is False


@pytest.mark.asyncio
async def test_non_account_entity_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The collector must ignore events that aren't Account instances."""
    from osint_core.entities.identifiers import Username

    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("username", "account", "url"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    WaybackCollector(bus).register()

    called = False

    async def fake_fetch(self, url: str):
        nonlocal called
        called = True
        return [{"timestamp": "20200101000000", "original": "x"}]

    monkeypatch.setattr(WaybackCollector, "_fetch_snapshots", fake_fetch)

    u = Username(value="alice", evidence=[Evidence(collector="test", confidence=1.0)])
    await bus.publish(EntityDiscovered(entity=u, origin_collector="test"))
    await bus.drain()
    assert called is False


def test_build_archive_url_format() -> None:
    snap = {"timestamp": "20200101123456", "original": "https://github.com/alice"}
    url = WaybackCollector._build_archive_url(snap)
    assert url == "https://web.archive.org/web/20200101123456/https://github.com/alice"


def test_pretty_timestamp() -> None:
    assert WaybackCollector._pretty_timestamp("20200305123456") == "2020-03-05"
    assert WaybackCollector._pretty_timestamp("") == "?"
    assert WaybackCollector._pretty_timestamp("short") == "short"
