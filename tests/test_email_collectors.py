"""Tests for email-based collectors."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.email.domain_extractor import EmailDomainExtractor
from osint_core.collectors.email.gravatar import GravatarCollector
from osint_core.collectors.enrichment.fetchers import FetchResult, ProfileFetcher
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email
from osint_core.storage.memory import InMemoryGraphStore


# ---------------------------------------------------------------------------
# EmailDomainExtractor — no network
# ---------------------------------------------------------------------------


def _email_event(addr: str) -> EntityDiscovered:
    return EntityDiscovered(
        entity=Email(
            value=addr,
            evidence=[Evidence(collector="seed", confidence=1.0)],
        ),
        origin_collector="test",
    )


async def _wire_domain_extractor() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email", "domain"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    EmailDomainExtractor(bus).register()
    return bus, store


@pytest.mark.asyncio
async def test_domain_extractor_emits_domain() -> None:
    bus, store = await _wire_domain_extractor()
    await bus.publish(_email_event("alice@example.com"))
    await bus.drain()
    [domain] = store.by_type("domain")
    assert domain.value == "example.com"
    assert domain.metadata["disposable"] is False


@pytest.mark.asyncio
async def test_domain_extractor_flags_disposable() -> None:
    bus, store = await _wire_domain_extractor()
    await bus.publish(_email_event("throwaway@mailinator.com"))
    await bus.drain()
    [domain] = store.by_type("domain")
    assert domain.metadata["disposable"] is True
    assert "disposable provider" in domain.evidence[0].notes


@pytest.mark.asyncio
async def test_domain_extractor_accepts_custom_disposable_set() -> None:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email", "domain"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    EmailDomainExtractor(bus, disposable_domains={"acme.test"}).register()

    await bus.publish(_email_event("a@acme.test"))
    await bus.drain()
    [domain] = store.by_type("domain")
    assert domain.metadata["disposable"] is True


# ---------------------------------------------------------------------------
# GravatarCollector — mocked HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gravatar_exists_emits_account(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email", "account"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)

    collector = GravatarCollector(bus)

    async def fake_exists(self, url: str) -> bool:
        return True

    monkeypatch.setattr(GravatarCollector, "_gravatar_exists", fake_exists)
    collector.register()

    seed_email = Email(
        value="alice@example.com",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    store.add_entity(seed_email)
    await bus.publish(
        EntityDiscovered(entity=seed_email, origin_collector="test")
    )
    await bus.drain()

    [account] = store.by_type("account")
    assert account.platform == "gravatar"
    # MD5("alice@example.com") — precomputed
    import hashlib
    expected_hash = hashlib.md5(b"alice@example.com").hexdigest()
    assert account.username == expected_hash
    assert f"gravatar.com/avatar/{expected_hash}" in account.avatar_url
    assert account.evidence[0].raw_data["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_gravatar_missing_emits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email", "account"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)

    async def fake_exists(self, url: str) -> bool:
        return False

    monkeypatch.setattr(GravatarCollector, "_gravatar_exists", fake_exists)
    GravatarCollector(bus).register()

    await bus.publish(_email_event("nobody@example.com"))
    await bus.drain()
    assert store.by_type("account") == []


@pytest.mark.asyncio
async def test_gravatar_normalizes_email_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gravatar spec: email is lowercased and trimmed before MD5."""
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("email", "account"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)

    captured_urls: list[str] = []

    async def fake_exists(self, url: str) -> bool:
        captured_urls.append(url)
        return True

    monkeypatch.setattr(GravatarCollector, "_gravatar_exists", fake_exists)
    GravatarCollector(bus).register()

    # The Email validator already lowercases — so this test basically
    # confirms we don't undo that work.
    await bus.publish(_email_event("Alice@Example.COM"))
    await bus.drain()

    import hashlib
    expected_hash = hashlib.md5(b"alice@example.com").hexdigest()
    assert any(expected_hash in u for u in captured_urls)


# ---------------------------------------------------------------------------
# ProfileFetcher._fetch_gravatar — parses the profile JSON correctly
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = ""

    def json(self) -> dict:
        return self._json


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        return self._response


@pytest.mark.asyncio
async def test_fetch_gravatar_parses_profile_json() -> None:
    fake_json = {
        "entry": [
            {
                "displayName": "Alice Example",
                "preferredUsername": "alice",
                "aboutMe": "Python developer based in Berlin.",
                "currentLocation": "Berlin, DE",
                "thumbnailUrl": "https://secure.gravatar.com/avatar/abc",
                "urls": [{"title": "Blog", "value": "https://alice.dev"}],
                "accounts": [
                    {
                        "shortname": "github",
                        "url": "https://github.com/alicedev",
                        "username": "alicedev",
                    },
                    {
                        "shortname": "twitter",
                        "url": "https://twitter.com/alice_tweets",
                        "username": "alice_tweets",
                    },
                ],
            }
        ]
    }
    fetcher = ProfileFetcher(client=_FakeClient(_FakeResponse(200, fake_json)))
    result = await fetcher._fetch_gravatar("deadbeefcafe")

    assert result.status == 200
    assert result.display_name == "Alice Example"
    assert result.avatar_url == "https://secure.gravatar.com/avatar/abc"
    # Bio aggregates everything searchable by extractors
    assert "Alice Example" in result.bio
    assert "Berlin" in result.bio
    assert "https://alice.dev" in result.bio
    assert "https://github.com/alicedev" in result.bio
    assert "@alicedev" in result.bio
    assert "@alice_tweets" in result.bio
    assert result.extras["linked_accounts"] == ["github", "twitter"]


@pytest.mark.asyncio
async def test_fetch_gravatar_handles_empty_entry() -> None:
    fetcher = ProfileFetcher(client=_FakeClient(_FakeResponse(200, {"entry": []})))
    result = await fetcher._fetch_gravatar("abc")
    assert result.status == 404


@pytest.mark.asyncio
async def test_fetch_gravatar_handles_404() -> None:
    fetcher = ProfileFetcher(client=_FakeClient(_FakeResponse(404, {})))
    result = await fetcher._fetch_gravatar("abc")
    assert result.status == 404
