"""Tests for the GitHubCommitsCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.github_commits import GitHubCommitsCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _github_account(username: str = "alice") -> Account:
    return Account(
        value=f"github:{username.lower()}",
        platform="github",
        username=username,
        profile_url=f"https://github.com/{username}",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


def _other_account() -> Account:
    return Account(
        value="twitter:alice",
        platform="twitter",
        username="alice",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _wire(
    collector: GitHubCommitsCollector | None = None,
) -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("account", "email"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    col = collector or GitHubCommitsCollector(bus, relationship_sink=store)
    col.register()
    return bus, store


async def _publish(bus: EventBus, store: InMemoryGraphStore, account: Account) -> None:
    store.add_entity(account)
    await bus.publish(EntityDiscovered(entity=account, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extracts_emails_from_push_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    fake_events = [
        {
            "type": "PushEvent",
            "repo": {"name": "alice/myrepo"},
            "payload": {
                "commits": [
                    {
                        "sha": "abc123",
                        "author": {"email": "alice.real@example.com", "name": "Alice"},
                    },
                    {
                        "sha": "def456",
                        "author": {"email": "alice.real@example.com", "name": "Alice"},
                    },
                ]
            },
        },
        {
            "type": "PushEvent",
            "repo": {"name": "alice/sideproject"},
            "payload": {
                "commits": [
                    {
                        "sha": "789",
                        "author": {"email": "alice@work.co", "name": "Alice"},
                    }
                ]
            },
        },
        # Non-push events should be ignored
        {"type": "WatchEvent", "payload": {}},
    ]

    async def fake_fetch(self, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        return fake_events

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _github_account("alice"))

    emails = {e.value for e in store.by_type("email")}
    assert emails == {"alice.real@example.com", "alice@work.co"}

    # The one that appeared twice should have higher confidence than the single-commit one
    by_val = {e.value: e for e in store.by_type("email")}
    assert by_val["alice.real@example.com"].confidence > by_val["alice@work.co"].confidence

    # commits_as edges were emitted for each email
    commits_edges = [r for r in store.relationships if r.predicate == "commits_as"]
    assert len(commits_edges) == 2
    # Metadata carries the commit count
    counts = sorted(r.metadata["commits_observed"] for r in commits_edges)
    assert counts == [1, 2]


@pytest.mark.asyncio
async def test_skips_noreply_masked_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()
    fake_events = [
        {
            "type": "PushEvent",
            "repo": {"name": "alice/repo"},
            "payload": {
                "commits": [
                    {
                        "sha": "a",
                        "author": {
                            "email": "1234+alice@users.noreply.github.com",
                            "name": "Alice",
                        },
                    },
                    {
                        "sha": "b",
                        "author": {"email": "alice@users.noreply.github.com", "name": "Alice"},
                    },
                ]
            },
        }
    ]

    async def fake_fetch(self, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        return fake_events

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _github_account("alice"))
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_ignores_non_github_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    called = False

    async def fake_fetch(self, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _other_account())
    assert called is False
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_handles_empty_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, url: str, headers: dict[str, str]):
        return []

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _github_account("ghost"))
    assert store.by_type("email") == []


@pytest.mark.asyncio
async def test_handles_api_failure_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A None return from _fetch_events (rate-limit, error) must not crash."""
    bus, store = await _wire()

    async def fake_fetch(self, url: str, headers: dict[str, str]):
        return None

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _github_account("alice"))
    assert store.by_type("email") == []
    assert [r for r in store.relationships if r.predicate == "commits_as"] == []


@pytest.mark.asyncio
async def test_malformed_emails_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, url: str, headers: dict[str, str]):
        return [
            {
                "type": "PushEvent",
                "repo": {"name": "alice/repo"},
                "payload": {
                    "commits": [
                        {"sha": "x", "author": {"email": "not-an-email"}},
                        {"sha": "y", "author": {"email": ""}},
                        {"sha": "z", "author": {"email": "ok@example.com"}},
                    ]
                },
            }
        ]

    monkeypatch.setattr(GitHubCommitsCollector, "_fetch_events", fake_fetch)

    await _publish(bus, store, _github_account("alice"))
    assert {e.value for e in store.by_type("email")} == {"ok@example.com"}
