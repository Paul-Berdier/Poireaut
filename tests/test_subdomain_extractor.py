"""Tests for the SubdomainExtractor."""

from __future__ import annotations

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.domain.subdomain_extractor import SubdomainExtractor
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain
from osint_core.storage.memory import InMemoryGraphStore


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    bus.subscribe("domain", lambda e: store.add_event(e), dedup=False)
    SubdomainExtractor(bus, relationship_sink=store).register()
    return bus, store


def _domain_with_certs(value: str, cns: list[str]) -> Domain:
    return Domain(
        value=value,
        metadata={
            "certificates": [{"common_name": cn} for cn in cns],
        },
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _publish(bus: EventBus, store: InMemoryGraphStore, domain: Domain) -> None:
    store.add_entity(domain)
    await bus.publish(EntityDiscovered(entity=domain, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotes_subdomains_and_links_them() -> None:
    bus, store = await _wire()

    parent = _domain_with_certs(
        "example.com",
        [
            "api.example.com",
            "staging.example.com",
            "example.com",            # parent itself — filtered
            "*.example.com",          # wildcard — filtered
            "evil.other.com",         # unrelated — filtered
            "admin.staging.example.com",
            "api.example.com",        # duplicate — filtered
        ],
    )
    await _publish(bus, store, parent)

    domains = {d.value for d in store.by_type("domain")}
    # Parent + 3 legitimate subdomains
    assert domains == {
        "example.com",
        "api.example.com",
        "staging.example.com",
        "admin.staging.example.com",
    }

    # subdomain_of edges: one per newly-emitted subdomain
    sub_edges = [r for r in store.relationships if r.predicate == "subdomain_of"]
    assert len(sub_edges) == 3


@pytest.mark.asyncio
async def test_handles_multi_value_common_names() -> None:
    """crt.sh sometimes packs multiple SANs into a single common_name separated
    by commas or newlines. Note: Domain normalizes away leading `www.` (see
    test_entities.py), so a `www.company.io` SAN collapses onto the parent and
    is correctly deduped rather than emitted as a separate node."""
    bus, store = await _wire()

    parent = _domain_with_certs(
        "company.io",
        ["www.company.io,api.company.io", "mail.company.io\nportal.company.io"],
    )
    await _publish(bus, store, parent)

    domains = {d.value for d in store.by_type("domain")}
    assert {
        "api.company.io",
        "mail.company.io",
        "portal.company.io",
    }.issubset(domains)
    # www.company.io normalizes to company.io (the parent) and is filtered.
    assert "www.company.io" not in domains


@pytest.mark.asyncio
async def test_no_certificates_is_noop() -> None:
    bus, store = await _wire()

    parent = Domain(
        value="nocerts.com",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, parent)
    assert {d.value for d in store.by_type("domain")} == {"nocerts.com"}
    assert [r for r in store.relationships if r.predicate == "subdomain_of"] == []


@pytest.mark.asyncio
async def test_flag_prevents_double_emission() -> None:
    """Re-publishing a domain whose subdomains were already emitted is a noop."""
    bus, store = await _wire()

    parent = _domain_with_certs("example.com", ["api.example.com"])
    await _publish(bus, store, parent)

    # Re-publish the same entity — the internal flag should short-circuit.
    await bus.publish(EntityDiscovered(entity=parent, origin_collector="test"))
    await bus.drain()

    # Still exactly one subdomain + one edge (no duplicates).
    sub_edges = [r for r in store.relationships if r.predicate == "subdomain_of"]
    assert len(sub_edges) == 1


@pytest.mark.asyncio
async def test_invalid_subdomain_names_are_dropped() -> None:
    bus, store = await _wire()

    parent = _domain_with_certs(
        "example.com",
        [
            "legit.example.com",
            "bad space.example.com",     # space invalid
            "trailing-dot.example.com.",  # trailing dot stripped → OK
            "good.example.com",
        ],
    )
    await _publish(bus, store, parent)

    domains = {d.value for d in store.by_type("domain")}
    assert "legit.example.com" in domains
    assert "good.example.com" in domains
    assert "trailing-dot.example.com" in domains
    # The invalid one must have been rejected
    assert not any("bad space" in d for d in domains)
