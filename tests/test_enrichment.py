"""End-to-end enrichment tests with a mocked fetcher.

We verify that an Account flowing through the bus triggers the enrichment
collector, which extracts sub-entities and re-emits them, and that the
store accumulates everything correctly.
"""

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.fetchers import FetchResult, ProfileFetcher
from osint_core.collectors.enrichment.profile import ProfileEnrichmentCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


class StubFetcher(ProfileFetcher):
    """Fetcher that returns canned data — no HTTP."""

    def __init__(self, canned: FetchResult) -> None:
        self.canned = canned
        self.calls: list[tuple[str, str, str]] = []

    async def fetch(self, platform, username, profile_url):
        self.calls.append((platform, username, profile_url))
        return self.canned


async def _wire_investigation(fetcher: ProfileFetcher) -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()

    async def _on_any(event):
        store.add_entity(event.entity)

    for t in ("username", "email", "phone", "domain", "url", "ip",
              "account", "person", "location", "image"):
        bus.subscribe(t, _on_any, dedup=False)

    collector = ProfileEnrichmentCollector(bus, fetcher=fetcher)
    collector.register()
    return bus, store


@pytest.mark.asyncio
async def test_enrichment_extracts_email_and_url_and_location() -> None:
    fetcher = StubFetcher(
        FetchResult(
            status=200,
            fetched_url="https://api.github.com/users/alice",
            bio=(
                "Developer based in Paris.\n"
                "Contact: alice@example.com\n"
                "Blog: https://alice.dev\n"
                "Find me on twitter @alicecode"
            ),
            display_name="Alice Example",
            avatar_url="https://avatars.example.com/alice.png",
            followers=123,
        )
    )
    bus, store = await _wire_investigation(fetcher)

    seed = Account(
        value="github:alice",
        platform="github",
        username="alice",
        profile_url="https://github.com/alice",
        evidence=[Evidence(collector="test_seed", confidence=1.0)],
    )
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="test"))
    await bus.drain()

    # The account is upgraded in place (merged with display_name etc.)
    [acc] = store.by_type("account")
    assert acc.display_name == "Alice Example"
    assert acc.avatar_url == "https://avatars.example.com/alice.png"
    assert acc.followers_count == 123

    # Sub-entities are discovered
    emails = store.by_type("email")
    assert [e.value for e in emails] == ["alice@example.com"]

    urls = store.by_type("url")
    assert [u.value for u in urls] == ["https://alice.dev"]

    locations = store.by_type("location")
    assert len(locations) == 1
    assert locations[0].value == "Paris"
    assert locations[0].country == "FR"

    usernames = [u.value for u in store.by_type("username")]
    assert "alicecode" in usernames


@pytest.mark.asyncio
async def test_enrichment_skips_unsupported_platform() -> None:
    fetcher = StubFetcher(FetchResult(status=200, fetched_url="x", bio="hello"))
    bus, store = await _wire_investigation(fetcher)

    seed = Account(
        value="random:alice",
        platform="random_unknown",
        username="alice",
        profile_url="https://random.example/alice",
        evidence=[Evidence(collector="test_seed", confidence=1.0)],
    )
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="test"))
    await bus.drain()

    # Fetcher must not have been called
    assert fetcher.calls == []
    # No sub-entities produced
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_enrichment_evidence_preserves_provenance() -> None:
    fetcher = StubFetcher(
        FetchResult(
            status=200,
            fetched_url="https://api.github.com/users/alice",
            bio="alice@example.com",
        )
    )
    bus, store = await _wire_investigation(fetcher)
    seed = Account(
        value="github:alice",
        platform="github",
        username="alice",
        profile_url="https://github.com/alice",
        evidence=[Evidence(collector="test_seed", confidence=1.0)],
    )
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="test"))
    await bus.drain()

    [email] = store.by_type("email")
    assert len(email.evidence) == 1
    ev = email.evidence[0]
    assert ev.collector == "profile_enrichment"
    assert ev.source_url == "https://api.github.com/users/alice"
    assert "email" in ev.raw_data.get("extractor", "")
    assert ev.raw_data.get("source_account") == "github:alice"
