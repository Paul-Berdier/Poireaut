"""Tests for the KeybaseCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.keybase import KeybaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account
from osint_core.storage.memory import InMemoryGraphStore


def _keybase_account(username: str = "alice") -> Account:
    return Account(
        value=f"keybase:{username.lower()}",
        platform="keybase",
        username=username,
        profile_url=f"https://keybase.io/{username}",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("account", "url"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    KeybaseCollector(bus, relationship_sink=store).register()
    return bus, store


async def _publish(bus: EventBus, store: InMemoryGraphStore, account: Account) -> None:
    store.add_entity(account)
    await bus.publish(EntityDiscovered(entity=account, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_accounts_for_verified_proofs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    fake_api_payload: dict[str, Any] = {
        "status": {"code": 0, "name": "OK"},
        "them": [
            {
                "basics": {"username": "alice"},
                "proofs_summary": {
                    "all": [
                        {
                            "proof_type": "twitter",
                            "nametag": "alice_tweets",
                            "service_url": "https://twitter.com/alice_tweets",
                            "presentation_url": "https://twitter.com/alice_tweets/status/123",
                            "state": 1,
                        },
                        {
                            "proof_type": "github",
                            "nametag": "alice_dev",
                            "service_url": "https://github.com/alice_dev",
                            "presentation_url": "https://gist.github.com/alice_dev/xxx",
                            "state": 1,
                        },
                        # Broken proof — state != 1 must be skipped.
                        {
                            "proof_type": "reddit",
                            "nametag": "alice_old",
                            "service_url": "https://reddit.com/user/alice_old",
                            "state": 2,
                        },
                    ]
                },
            }
        ],
    }

    async def fake_fetch(self, url: str) -> dict[str, Any]:
        return fake_api_payload

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)

    await _publish(bus, store, _keybase_account("alice"))

    accounts = {a.platform.lower(): a for a in store.by_type("account")}
    assert "twitter" in accounts
    assert "github" in accounts
    # Broken proof skipped
    assert "reddit" not in accounts

    # Relationship edges: one cross_verified_by per verified proof
    cross_edges = [r for r in store.relationships if r.predicate == "cross_verified_by"]
    assert len(cross_edges) == 2
    twitter_edge = next(
        r for r in cross_edges if r.metadata.get("proof_type") == "twitter"
    )
    assert twitter_edge.evidence[0].confidence >= 0.9

    # Both discovered accounts flag themselves as keybase-verified
    for platform in ("twitter", "github"):
        assert accounts[platform].metadata.get("keybase_verified") is True


@pytest.mark.asyncio
async def test_emits_url_for_website_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, url: str) -> dict[str, Any]:
        return {
            "status": {"code": 0, "name": "OK"},
            "them": [
                {
                    "basics": {"username": "alice"},
                    "proofs_summary": {
                        "all": [
                            {
                                "proof_type": "generic_web_site",
                                "nametag": "alice.dev",
                                "service_url": "https://alice.dev",
                                "presentation_url": "https://alice.dev/keybase.txt",
                                "state": 1,
                            },
                            {
                                "proof_type": "dns",
                                "nametag": "example.org",
                                "service_url": "https://example.org",
                                "state": 1,
                            },
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)

    await _publish(bus, store, _keybase_account("alice"))

    urls = {u.value for u in store.by_type("url")}
    assert "https://alice.dev" in urls
    assert "https://example.org" in urls


@pytest.mark.asyncio
async def test_ignores_non_keybase_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    called = False

    async def fake_fetch(self, url: str):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)

    other = Account(
        value="github:alice",
        platform="github",
        username="alice",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, other)
    assert called is False


@pytest.mark.asyncio
async def test_handles_empty_them_array(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Keybase returns status.code=0 but the user doesn't exist, `them` is empty."""
    bus, store = await _wire()

    async def fake_fetch(self, url: str):
        return {"status": {"code": 0}, "them": []}

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _keybase_account("nobody"))

    # Only the seed Keybase account (which we inserted) is in store.
    accts = store.by_type("account")
    assert len(accts) == 1
    assert accts[0].platform == "keybase"


@pytest.mark.asyncio
async def test_handles_null_them_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keybase sometimes returns `them: [null]` for unresolved usernames."""
    bus, store = await _wire()

    async def fake_fetch(self, url: str):
        return {"status": {"code": 0}, "them": [None]}

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _keybase_account("nobody"))

    accts = store.by_type("account")
    assert len(accts) == 1  # only the seed


@pytest.mark.asyncio
async def test_malformed_url_in_website_proof_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    async def fake_fetch(self, url: str):
        return {
            "status": {"code": 0},
            "them": [
                {
                    "basics": {"username": "alice"},
                    "proofs_summary": {
                        "all": [
                            {
                                "proof_type": "generic_web_site",
                                "nametag": "",  # no usable value
                                "state": 1,
                            }
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(KeybaseCollector, "_fetch", fake_fetch)
    await _publish(bus, store, _keybase_account("alice"))
    assert store.by_type("url") == []
