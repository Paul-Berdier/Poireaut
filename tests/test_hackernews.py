"""Tests for the HackerNewsCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.hackernews import HackerNewsCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


def _hn_account(username: str = "pg") -> Account:
    return Account(
        value=f"hackernews:{username.lower()}",
        platform="hackernews",
        username=username,
        profile_url=f"https://news.ycombinator.com/user?id={username}",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("account", "email", "url", "location", "username"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    HackerNewsCollector(bus).register()
    return bus, store


async def _publish(bus: EventBus, store: InMemoryGraphStore, account: Account) -> None:
    store.add_entity(account)
    await bus.publish(EntityDiscovered(entity=account, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enriches_account_with_karma_and_bio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    fake_data = {
        "id": "alice",
        "karma": 4321,
        "created": 1700000000,
        "about": (
            'Python dev in Paris. Reach me at <a href="mailto:alice@example.com">'
            'alice@example.com</a> or on my <a href="https://alice.dev">blog</a>.'
        ),
    }

    async def fake_fetch(self, username: str) -> dict[str, Any]:
        assert username == "alice"
        return fake_data

    monkeypatch.setattr(HackerNewsCollector, "_fetch", fake_fetch)

    await _publish(bus, store, _hn_account("alice"))

    [account] = [a for a in store.by_type("account") if a.platform.lower() == "hackernews"]
    assert account.metadata.get("hn_karma") == 4321
    assert account.metadata.get("enriched") is True
    assert account.bio and "Python dev in Paris" in account.bio
    # HTML tags stripped
    assert "<a" not in (account.bio or "")

    # Extractors fired against the cleaned bio.
    assert {e.value for e in store.by_type("email")} == {"alice@example.com"}
    urls = {u.value for u in store.by_type("url")}
    assert "https://alice.dev" in urls
    locations = {loc.value for loc in store.by_type("location")}
    assert "Paris" in locations


@pytest.mark.asyncio
async def test_ignores_non_hackernews_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    called = False

    async def fake_fetch(self, username: str):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(HackerNewsCollector, "_fetch", fake_fetch)

    other = Account(
        value="twitter:alice",
        platform="twitter",
        username="alice",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, other)
    assert called is False


@pytest.mark.asyncio
async def test_handles_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """HN's Firebase API returns `null` (→ None) for unknown users."""
    bus, store = await _wire()

    async def fake_fetch(self, username: str):
        return None

    monkeypatch.setattr(HackerNewsCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _hn_account("nobody"))

    # Only the seed HN account we planted is present.
    accts = store.by_type("account")
    assert len(accts) == 1
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_handles_empty_about_field(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, username: str):
        return {"id": "alice", "karma": 10, "created": 1700000000, "about": ""}

    monkeypatch.setattr(HackerNewsCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _hn_account("alice"))

    # Account is still upgraded with karma, but no sub-entities extracted.
    [account] = [a for a in store.by_type("account") if a.platform.lower() == "hackernews"]
    assert account.metadata.get("hn_karma") == 10
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_handles_invalid_created_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A junk `created` field should not raise — metadata just omits the ISO date."""
    bus, store = await _wire()

    async def fake_fetch(self, username: str):
        return {
            "id": "alice",
            "karma": 1,
            "created": "not-a-number",
            "about": "hello",
        }

    monkeypatch.setattr(HackerNewsCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _hn_account("alice"))

    [account] = [a for a in store.by_type("account") if a.platform.lower() == "hackernews"]
    assert account.metadata.get("hn_created_at") is None


def test_strip_tags_handles_common_entities() -> None:
    # Tag-stripping inserts spaces around tag boundaries, so "<i>friends</i>'s"
    # normalizes to "friends 's" after whitespace collapse. That's acceptable —
    # downstream extractors tokenize on whitespace anyway.
    stripped = HackerNewsCollector._strip_tags(
        "Hello&nbsp;<b>World</b>&amp; friends's project"
    )
    assert stripped == "Hello World & friends's project"


def test_strip_tags_preserves_href_urls() -> None:
    """HN bios often put the only URL in the `href` attribute."""
    stripped = HackerNewsCollector._strip_tags(
        'Check my <a href="https://alice.dev" rel="nofollow">blog</a> '
        'or email <a href="mailto:alice@example.com">me</a>.'
    )
    assert "https://alice.dev" in stripped
    assert "mailto:alice@example.com" in stripped


def test_strip_tags_ignores_non_http_hrefs() -> None:
    """Relative links and schemeless refs aren't re-appended."""
    stripped = HackerNewsCollector._strip_tags(
        'See <a href="#anchor">here</a> and <a href="/page">there</a>.'
    )
    assert "#anchor" not in stripped
    assert "/page" not in stripped
