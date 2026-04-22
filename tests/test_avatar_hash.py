"""Tests for the AvatarHashCollector.

We don't do any real network or image I/O — we stub `_download_and_hash`
to return controlled (phash_int, sha256, w, h) tuples and verify the
collector emits the right entities and relationships.
"""

from unittest.mock import AsyncMock

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.vision.avatar_hash import AvatarHashCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


# ---------------------------------------------------------------------------
# Pure functions: hamming distance, confidence curve
# ---------------------------------------------------------------------------


def test_hamming_distance_identical() -> None:
    assert AvatarHashCollector._hamming(0xFF, 0xFF) == 0


def test_hamming_distance_single_bit_flip() -> None:
    assert AvatarHashCollector._hamming(0b1010, 0b1011) == 1


def test_hamming_distance_opposite_64bit() -> None:
    assert AvatarHashCollector._hamming(0x0, 0xFFFFFFFFFFFFFFFF) == 64


def test_confidence_falloff() -> None:
    c0 = AvatarHashCollector._confidence_from_distance(0)
    c5 = AvatarHashCollector._confidence_from_distance(5)
    c10 = AvatarHashCollector._confidence_from_distance(10)
    assert c0 > c5 > c10
    assert c0 <= 0.98  # never claims absolute certainty
    assert c10 >= 0.4  # floor


# ---------------------------------------------------------------------------
# Integration: collector + bus + store, with stubbed image fetch
# ---------------------------------------------------------------------------


def _account_with_avatar(
    platform: str, username: str, avatar_url: str
) -> Account:
    return Account(
        value=f"{platform}:{username}",
        platform=platform,
        username=username,
        avatar_url=avatar_url,
        evidence=[Evidence(collector="test_seed", confidence=1.0)],
    )


def _make_event(entity, origin_id=None) -> EntityDiscovered:
    return EntityDiscovered(
        entity=entity,
        origin_collector="test",
        origin_entity_id=origin_id,
    )


async def _wire(hash_map: dict[str, int]) -> tuple[EventBus, InMemoryGraphStore, AvatarHashCollector]:
    """Create a wired bus+store+collector where _download_and_hash is stubbed
    from an URL→phash_int map."""
    bus = EventBus()
    store = InMemoryGraphStore()

    async def _on_any(event):
        store.add_event(event)

    for t in ("account", "image"):
        bus.subscribe(t, _on_any, dedup=False)

    collector = AvatarHashCollector(bus, relationship_sink=store)

    async def fake_download(url: str):
        if url in hash_map:
            return (hash_map[url], f"sha_{url}", 100, 100)
        return None

    collector._download_and_hash = fake_download  # type: ignore[assignment]
    collector.register()
    return bus, store, collector


@pytest.mark.asyncio
async def test_single_avatar_emits_image_and_no_relationship() -> None:
    bus, store, _ = await _wire({"https://avatar/a.png": 0xABCDEF0123456789})

    acc = _account_with_avatar("github", "alice", "https://avatar/a.png")
    store.add_entity(acc)
    await bus.publish(_make_event(acc))
    await bus.drain()

    images = store.by_type("image")
    assert len(images) == 1
    assert images[0].perceptual_hash == "abcdef0123456789"
    # No other avatars to correlate with yet
    assert [r for r in store.relationships if r.predicate == "same_avatar_as"] == []


@pytest.mark.asyncio
async def test_two_accounts_same_phash_emit_same_avatar_as() -> None:
    phash = 0xABCDEF0123456789
    bus, store, _ = await _wire(
        {
            "https://github.com/a.png":  phash,
            "https://gitlab.com/a.png":  phash,  # exact same hash, diff URL
        }
    )
    a = _account_with_avatar("github", "alice", "https://github.com/a.png")
    b = _account_with_avatar("gitlab", "alice", "https://gitlab.com/a.png")
    for acc in (a, b):
        store.add_entity(acc)
        await bus.publish(_make_event(acc))
    await bus.drain()

    same_avatar_edges = [r for r in store.relationships if r.predicate == "same_avatar_as"]
    assert len(same_avatar_edges) == 1
    edge = same_avatar_edges[0]
    assert {edge.source_id, edge.target_id} == {a.id, b.id}
    assert edge.metadata["hamming_distance"] == 0
    assert edge.metadata["match_type"] == "identical"
    assert edge.evidence[0].confidence >= 0.9


@pytest.mark.asyncio
async def test_close_but_not_identical_hashes_still_emit_relationship() -> None:
    # Two hashes differing in 3 bits — under IDENTICAL_THRESHOLD (4)
    h1 = 0x0
    h2 = 0b111  # 3 bits set → distance 3
    bus, store, _ = await _wire(
        {"https://x/a.png": h1, "https://x/b.png": h2}
    )
    a = _account_with_avatar("github", "alice", "https://x/a.png")
    b = _account_with_avatar("reddit", "alice", "https://x/b.png")
    for acc in (a, b):
        store.add_entity(acc)
        await bus.publish(_make_event(acc))
    await bus.drain()

    edges = [r for r in store.relationships if r.predicate == "same_avatar_as"]
    assert len(edges) == 1
    assert edges[0].metadata["hamming_distance"] == 3


@pytest.mark.asyncio
async def test_far_hashes_do_not_correlate() -> None:
    # Distance 20: way beyond SIMILAR_THRESHOLD (10)
    h1 = 0x0
    h2 = 0xFFFFF  # 20 bits set
    bus, store, _ = await _wire(
        {"https://x/a.png": h1, "https://x/b.png": h2}
    )
    a = _account_with_avatar("github", "alice", "https://x/a.png")
    b = _account_with_avatar("reddit", "alice", "https://x/b.png")
    for acc in (a, b):
        store.add_entity(acc)
        await bus.publish(_make_event(acc))
    await bus.drain()

    assert [r for r in store.relationships if r.predicate == "same_avatar_as"] == []


@pytest.mark.asyncio
async def test_account_without_avatar_is_skipped() -> None:
    bus, store, collector = await _wire({})
    acc = Account(
        value="github:bob",
        platform="github",
        username="bob",
        # no avatar_url
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    store.add_entity(acc)
    await bus.publish(_make_event(acc))
    await bus.drain()
    assert store.by_type("image") == []


@pytest.mark.asyncio
async def test_url_dedup_avoids_redownload() -> None:
    """Enrichment may re-emit an Account multiple times; we must not
    redownload the same avatar each time."""
    call_count = {"n": 0}
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("account", "image"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)

    collector = AvatarHashCollector(bus, relationship_sink=store)

    async def fake_download(url: str):
        call_count["n"] += 1
        return (0xDEADBEEF, f"sha_{url}", 50, 50)

    collector._download_and_hash = fake_download  # type: ignore[assignment]
    collector.register()

    acc = _account_with_avatar("github", "alice", "https://x/a.png")
    store.add_entity(acc)
    # Publish 3 times — simulating enrichment repeatedly upgrading the same account
    for _ in range(3):
        await bus.publish(_make_event(acc))
    await bus.drain()

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_collector_without_sink_drops_relationships_silently() -> None:
    """emit_relationship with sink=None should just log and move on."""
    bus = EventBus()
    collector = AvatarHashCollector(bus, relationship_sink=None)  # no sink

    rel = Relationship(
        source_id=_account_with_avatar("a", "x", "u").id,
        target_id=_account_with_avatar("b", "x", "u").id,
        predicate="same_avatar_as",
    )
    # Should not raise
    collector.emit_relationship(rel)
