"""Tests for UrlscanCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.urlscan import UrlscanCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Url
from osint_core.storage.memory import InMemoryGraphStore


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("url", "domain", "ip", "location"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    UrlscanCollector(bus).register()
    return bus, store


def _url(v: str = "https://alice.dev") -> Url:
    return Url(value=v, evidence=[Evidence(collector="test", confidence=1.0)])


async def _publish(bus: EventBus, store: InMemoryGraphStore, u: Url) -> None:
    store.add_entity(u)
    await bus.publish(EntityDiscovered(entity=u, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_domain_ip_and_country(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_search(self, url: str) -> dict[str, Any]:
        return {
            "page": {
                "domain": "alice.dev",
                "ip": "185.230.63.107",
                "country": "FR",
                "server": "nginx/1.21",
            },
            "result": "https://urlscan.io/result/abc-123",
            "screenshot": "https://urlscan.io/screenshots/abc.png",
        }

    monkeypatch.setattr(UrlscanCollector, "_search_one", fake_search)

    await _publish(bus, store, _url("https://alice.dev/about"))

    domains = {d.value for d in store.by_type("domain")}
    ips = {ip.value for ip in store.by_type("ip")}
    locs = {loc.value for loc in store.by_type("location")}
    assert "alice.dev" in domains
    assert "185.230.63.107" in ips
    assert "FR" in locs

    # Url entity itself enriched with scan permalink + screenshot
    [url] = store.by_type("url")
    assert url.metadata["urlscan_report"] == "https://urlscan.io/result/abc-123"
    assert url.metadata["urlscan_screenshot"].endswith("abc.png")


@pytest.mark.asyncio
async def test_skips_noise_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known infrastructure hosts like github.com are skipped without an HTTP call."""
    bus, store = await _wire()

    called = False

    async def fake_search(self, url: str):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(UrlscanCollector, "_search_one", fake_search)
    await _publish(bus, store, _url("https://github.com/alice"))
    assert called is False
    assert store.by_type("domain") == []


@pytest.mark.asyncio
async def test_no_results_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_search(self, url: str):
        return None

    monkeypatch.setattr(UrlscanCollector, "_search_one", fake_search)
    await _publish(bus, store, _url("https://obscure.example"))
    assert store.by_type("domain") == []
    assert store.by_type("ip") == []


@pytest.mark.asyncio
async def test_partial_payload_tolerant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Urlscan may not always populate every field; we emit whatever we got."""
    bus, store = await _wire()

    async def fake_search(self, url: str):
        return {
            "page": {"domain": "foo.example", "ip": "", "country": ""},
            "result": "",
            "screenshot": "",
        }

    monkeypatch.setattr(UrlscanCollector, "_search_one", fake_search)
    await _publish(bus, store, _url("https://foo.example"))

    assert any(d.value == "foo.example" for d in store.by_type("domain"))
    # No IP / location emitted because the payload was missing them
    assert store.by_type("ip") == []
    assert store.by_type("location") == []


@pytest.mark.asyncio
async def test_invalid_ip_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_search(self, url: str):
        return {
            "page": {"domain": "foo.example", "ip": "not-an-ip", "country": ""},
        }

    monkeypatch.setattr(UrlscanCollector, "_search_one", fake_search)
    await _publish(bus, store, _url("https://foo.example"))
    assert store.by_type("ip") == []


def test_host_of_extracts_hostname() -> None:
    assert UrlscanCollector._host_of("https://alice.dev/about?x=1") == "alice.dev"
    assert UrlscanCollector._host_of("http://example.com:8080/a") == "example.com"
    assert UrlscanCollector._host_of("https://WWW.Example.com/") == "www.example.com"
    assert UrlscanCollector._host_of("bare-domain") == "bare-domain"
