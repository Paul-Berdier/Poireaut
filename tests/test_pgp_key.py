"""Tests for the PgpKeyCollector.

We use real PGP keys (generated with gpg) as fixtures so that the binary
packet parser is exercised against authentic output — not hand-crafted
byte sequences that might not match what real keyservers serve.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.email.pgp_key import PgpKeyCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email
from osint_core.storage.memory import InMemoryGraphStore


FIXTURES = Path(__file__).parent / "fixtures"
TWO_UIDS_KEY = (FIXTURES / "alice_two_uids.asc").read_text(encoding="utf-8")
SINGLE_UID_KEY = (FIXTURES / "bob_single_uid.asc").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Packet parser unit tests
# ---------------------------------------------------------------------------


def test_extract_uids_parses_two_uids() -> None:
    uids = PgpKeyCollector._extract_uids(TWO_UIDS_KEY)
    emails = {mail for _, mail in uids if mail}
    assert "alice@example.com" in emails
    assert "alice.backup@example.org" in emails


def test_extract_uids_parses_single_uid() -> None:
    uids = PgpKeyCollector._extract_uids(SINGLE_UID_KEY)
    emails = {mail for _, mail in uids if mail}
    assert emails == {"bob@solo.example"}


def test_extract_uids_returns_empty_on_junk() -> None:
    uids = PgpKeyCollector._extract_uids("not a pgp key block at all")
    assert uids == []


def test_regex_fallback_picks_up_obvious_email() -> None:
    """Even if the packet parser fails to decode, the regex sweep should
    surface any email clearly visible in the armored text."""
    corrupted = (
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n"
        "malformed body: eve@corrupted.example says hi\n"
        "-----END PGP PUBLIC KEY BLOCK-----\n"
    )
    uids = PgpKeyCollector._regex_fallback(corrupted)
    assert any(m == "eve@corrupted.example" for _, m in uids)


# ---------------------------------------------------------------------------
# End-to-end collector tests
# ---------------------------------------------------------------------------


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email",):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    PgpKeyCollector(bus, relationship_sink=store).register()
    return bus, store


def _seed_email(value: str) -> EntityDiscovered:
    return EntityDiscovered(
        entity=Email(
            value=value,
            evidence=[Evidence(collector="test", confidence=1.0)],
        ),
        origin_collector="test",
    )


@pytest.mark.asyncio
async def test_emits_bound_emails_and_relationships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, email_value: str):
        assert email_value == "alice@example.com"
        return TWO_UIDS_KEY

    monkeypatch.setattr(PgpKeyCollector, "_fetch_key", fake_fetch)

    seed = _seed_email("alice@example.com")
    store.add_entity(seed.entity)
    await bus.publish(seed)
    await bus.drain()

    emails = {e.value for e in store.by_type("email")}
    # Seed is there + the second UID from the key.
    assert emails == {"alice@example.com", "alice.backup@example.org"}

    pgp_edges = [r for r in store.relationships if r.predicate == "pgp_bound_to"]
    # One edge per bound email (only the non-seed UID here)
    assert len(pgp_edges) == 1
    assert pgp_edges[0].evidence[0].confidence >= 0.8

    # The seed now carries has_pgp_key = True
    seed_entity = next(e for e in store.by_type("email") if e.value == "alice@example.com")
    assert seed_entity.metadata.get("has_pgp_key") is True

    # The new email has a back-reference to its anchor
    bound = next(
        e for e in store.by_type("email") if e.value == "alice.backup@example.org"
    )
    assert bound.metadata.get("anchor_email") == "alice@example.com"


@pytest.mark.asyncio
async def test_handles_keyserver_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, email_value: str):
        return None  # 404 / not found

    monkeypatch.setattr(PgpKeyCollector, "_fetch_key", fake_fetch)

    seed = _seed_email("ghost@nowhere.test")
    store.add_entity(seed.entity)
    await bus.publish(seed)
    await bus.drain()

    # No new emails added beyond the seed, no pgp edges.
    assert {e.value for e in store.by_type("email")} == {"ghost@nowhere.test"}
    assert [r for r in store.relationships if r.predicate == "pgp_bound_to"] == []


@pytest.mark.asyncio
async def test_single_uid_key_emits_no_bound_emails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the only UID on the key IS the seed, nothing new is emitted."""
    bus, store = await _wire()

    async def fake_fetch(self, email_value: str):
        return SINGLE_UID_KEY

    monkeypatch.setattr(PgpKeyCollector, "_fetch_key", fake_fetch)

    seed = _seed_email("bob@solo.example")
    store.add_entity(seed.entity)
    await bus.publish(seed)
    await bus.drain()

    # Seed keeps the has_pgp_key flag though.
    bob = next(e for e in store.by_type("email") if e.value == "bob@solo.example")
    assert bob.metadata.get("has_pgp_key") is True
    # No extra emails emitted, no edges.
    assert {e.value for e in store.by_type("email")} == {"bob@solo.example"}
    assert [r for r in store.relationships if r.predicate == "pgp_bound_to"] == []


@pytest.mark.asyncio
async def test_non_email_entities_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collector advertises consumes=['email'] so domains etc. never trigger it."""
    from osint_core.entities.identifiers import Domain

    bus = EventBus()
    store = InMemoryGraphStore()
    bus.subscribe("email", lambda e: store.add_event(e), dedup=False)
    bus.subscribe("domain", lambda e: store.add_event(e), dedup=False)
    PgpKeyCollector(bus).register()

    called = False

    async def fake_fetch(self, email_value: str):
        nonlocal called
        called = True
        return TWO_UIDS_KEY

    monkeypatch.setattr(PgpKeyCollector, "_fetch_key", fake_fetch)

    dom = Domain(
        value="example.com",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await bus.publish(EntityDiscovered(entity=dom, origin_collector="test"))
    await bus.drain()
    assert called is False
