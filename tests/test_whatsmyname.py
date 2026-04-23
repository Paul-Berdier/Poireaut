"""Tests for WhatsMyNameCollector.

The collector is the first one that uses WMN's dual-signal scheme
(e_code+e_string AND absence of m_string), so these tests exercise
each branch of that logic with a mocked httpx client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.username.whatsmyname import (
    WhatsMyNameCollector,
    _default_cache_path,
    load_wmn_data,
)
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Username
from osint_core.storage.memory import InMemoryGraphStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SITES_MIXED: list[dict[str, Any]] = [
    {
        "name": "GoodSite",
        "uri_check": "https://good.test/{account}",
        "uri_pretty": "https://good.test/profile/{account}",
        "e_code": 200,
        "e_string": "profile-page",
        "m_string": "not found",
        "m_code": 404,
        "cat": "social",
    },
    {
        "name": "AmbiguousSite",
        "uri_check": "https://ambig.test/{account}",
        "e_code": 200,
        "e_string": "profile-page",
        "m_string": "not found",
        "m_code": 404,
        "cat": "social",
    },
    {
        "name": "AbsentSite",
        "uri_check": "https://absent.test/{account}",
        "e_code": 200,
        "e_string": "exists-marker",
        "m_string": "Whoops, 404",
        "m_code": 404,
        "cat": "social",
    },
    {
        "name": "UsernameInString",
        "uri_check": "https://echo.test/{account}",
        "e_code": 200,
        "e_string": "\"login\":\"{account}\"",
        "m_string": "user not found",
        "m_code": 404,
        "cat": "coding",
    },
    {
        "name": "NsfwSite",
        "uri_check": "https://nsfw.test/{account}",
        "e_code": 200,
        "e_string": "anything",
        "m_string": "nope",
        "m_code": 404,
        "cat": "dating",
    },
]


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Maps URL → canned response. Used to stub httpx.AsyncClient."""

    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses
        self.seen_urls: list[str] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        self.seen_urls.append(url)
        try:
            return self._responses[url]
        except KeyError:
            raise httpx.TimeoutException("no mock") from None  # type: ignore[name-defined]

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        self.seen_urls.append(url + " [POST]")
        return self._responses.get(url, _FakeResponse(500, ""))


# Grab httpx only when needed; avoids import cost in cases where the
# stub is all the test uses.
try:
    import httpx  # noqa: F401
except ImportError:  # pragma: no cover
    pass


async def _run_collector(
    monkeypatch: pytest.MonkeyPatch,
    sites: list[dict[str, Any]],
    responses: dict[str, _FakeResponse],
    username: str = "alice",
    skip_categories: frozenset[str] | None = None,
) -> InMemoryGraphStore:
    """Spin up an event bus, wire WMN with mocked HTTP, drain."""
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("username", "account"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)

    client = _FakeClient(responses)

    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", lambda *a, **k: client)

    kwargs: dict[str, Any] = {"sites": sites, "concurrency": 4}
    if skip_categories is not None:
        kwargs["skip_categories"] = skip_categories
    WhatsMyNameCollector(bus, **kwargs).register()

    seed = Username(
        value=username,
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    store.add_entity(seed)
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="test"))
    await bus.drain()
    return store


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_signal_match_emits_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """e_string present AND m_string absent → positive hit."""
    responses = {
        "https://good.test/alice": _FakeResponse(
            200, "<html>profile-page here</html>"
        ),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[0]], responses)

    [acc] = [a for a in store.by_type("account") if a.platform == "GoodSite"]
    assert acc.username == "alice"
    assert acc.profile_url == "https://good.test/profile/alice"
    assert acc.evidence[0].collector == "whatsmyname"


@pytest.mark.asyncio
async def test_ambiguous_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Body contains BOTH the exists-marker AND the not-found marker: reject."""
    responses = {
        "https://ambig.test/alice": _FakeResponse(
            200,
            # Weird edge case — WMN's dual-signal rejects this because
            # m_string is present, even though e_string is also there.
            "profile-page but wait — not found",
        ),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[1]], responses)
    assert [a for a in store.by_type("account") if a.platform == "AmbiguousSite"] == []


@pytest.mark.asyncio
async def test_absent_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Body contains m_string (not found) → reject."""
    responses = {
        "https://absent.test/alice": _FakeResponse(404, "Whoops, 404"),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[2]], responses)
    assert store.by_type("account") == []


@pytest.mark.asyncio
async def test_username_template_in_estring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """e_string containing {account} is resolved against the queried username."""
    responses = {
        "https://echo.test/alice": _FakeResponse(
            200, '{"id": 1, "login":"alice", "bio":"..."}'
        ),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[3]], responses)
    assert any(
        a.platform == "UsernameInString" for a in store.by_type("account")
    )


@pytest.mark.asyncio
async def test_username_template_rejects_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the response quotes a DIFFERENT login, it's a false positive."""
    responses = {
        "https://echo.test/alice": _FakeResponse(
            200, '{"id": 1, "login":"admin", "bio":"..."}'
        ),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[3]], responses)
    assert [
        a for a in store.by_type("account") if a.platform == "UsernameInString"
    ] == []


@pytest.mark.asyncio
async def test_nsfw_category_skipped_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default skip_categories includes 'dating' — the probe must not fire."""
    client = _FakeClient({})
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "AsyncClient", lambda *a, **k: client)

    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("username", "account"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    WhatsMyNameCollector(bus, sites=[SITES_MIXED[4]], concurrency=2).register()

    seed = Username(
        value="alice", evidence=[Evidence(collector="t", confidence=1.0)]
    )
    store.add_entity(seed)
    await bus.publish(EntityDiscovered(entity=seed, origin_collector="t"))
    await bus.drain()

    assert client.seen_urls == []  # skipped entirely


@pytest.mark.asyncio
async def test_wrong_status_code_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correct body marker but HTTP 500 → no hit (e_code must match)."""
    responses = {
        "https://good.test/alice": _FakeResponse(500, "profile-page"),
    }
    store = await _run_collector(monkeypatch, [SITES_MIXED[0]], responses)
    assert [a for a in store.by_type("account") if a.platform == "GoodSite"] == []


# ---------------------------------------------------------------------------
# Data loader tests
# ---------------------------------------------------------------------------


def test_bundled_data_is_well_formed() -> None:
    """The fallback JSON shipped in the package must parse and carry sites."""
    sites, source = load_wmn_data(cache_path=Path("/nonexistent/path.json"))
    assert source == "bundled"
    assert len(sites) >= 10
    for s in sites:
        assert "name" in s
        assert "uri_check" in s
        assert "{account}" in s["uri_check"]


def test_cached_data_takes_precedence(tmp_path: Path) -> None:
    """A user cache file shadows the bundled one."""
    cache = tmp_path / "wmn.json"
    cache.write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "name": "CustomOnly",
                        "uri_check": "https://x/{account}",
                        "e_code": 200,
                        "cat": "test",
                    }
                ]
            }
        )
    )
    sites, source = load_wmn_data(cache_path=cache)
    assert source.startswith("cache:")
    assert [s["name"] for s in sites] == ["CustomOnly"]


def test_corrupted_cache_falls_back_to_bundled(tmp_path: Path) -> None:
    cache = tmp_path / "wmn.json"
    cache.write_text("{ this is not valid json")
    sites, source = load_wmn_data(cache_path=cache)
    assert source == "bundled"
    assert sites  # non-empty


def test_default_cache_path_under_home() -> None:
    path = _default_cache_path()
    assert path.name == "wmn-data.json"
    # Ends inside a directory named "osint-core"
    assert path.parent.name == "osint-core"
