"""Tests for FrenchCompanyLookupCollector."""

from __future__ import annotations

from typing import Any

import pytest

from osint_core.bus.dispatcher import EventBus
from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.enrichment.french_company import (
    FrenchCompanyLookupCollector,
)
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, Email
from osint_core.storage.memory import InMemoryGraphStore


# ---------------------------------------------------------------------------
# Sample API payload (trimmed) — mirrors the real response shape
# ---------------------------------------------------------------------------


SAMPLE_ACME = {
    "results": [
        {
            "siren": "123456789",
            "nom_complet": "Acme France SARL",
            "nom_raison_sociale": "ACME FRANCE",
            "nature_juridique": "5710",
            "date_creation": "2015-06-12",
            "etat_administratif": "A",
            "categorie_entreprise": "PME",
            "activite_principale": "62.02A",
            "tranche_effectif_salarie": "03",
            "siege": {
                "libelle_commune": "PARIS",
                "code_postal": "75001",
                "geo_adresse": "10 RUE DE RIVOLI 75001 PARIS",
            },
            "dirigeants": [
                {
                    "nom": "Dupont",
                    "prenoms": "Marie",
                    "qualite": "Présidente",
                    "annee_de_naissance": "1980",
                    "nationalite": "Française",
                },
                {
                    "nom": "Durand",
                    "prenoms": "Jean-Pierre",
                    "qualite": "Directeur général",
                    "annee_de_naissance": "1975",
                    "nationalite": "Française",
                },
                # Moral-person director — must be silently skipped.
                {
                    "denomination": "HOLDING XYZ",
                    "siren": "987654321",
                    "qualite": "Administrateur",
                },
            ],
        }
    ]
}


SAMPLE_UNRELATED = {
    "results": [
        {
            "siren": "000000000",
            "nom_complet": "UNRELATED COMPANY TOTALLY",
            "nature_juridique": "5710",
            "siege": {"libelle_commune": "LILLE", "code_postal": "59000"},
            "dirigeants": [],
        }
    ]
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wire() -> tuple[EventBus, InMemoryGraphStore]:
    bus = EventBus()
    store = InMemoryGraphStore()
    for t in ("domain", "email", "organization", "person", "location"):
        bus.subscribe(t, lambda e: store.add_event(e), dedup=False)
    FrenchCompanyLookupCollector(bus, relationship_sink=store).register()
    return bus, store


def _domain(value: str) -> Domain:
    return Domain(
        value=value,
        evidence=[Evidence(collector="test", confidence=1.0)],
    )


async def _publish(
    bus: EventBus, store: InMemoryGraphStore, entity: Any
) -> None:
    store.add_entity(entity)
    await bus.publish(EntityDiscovered(entity=entity, origin_collector="test"))
    await bus.drain()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_organization_directors_and_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    async def fake_search(self, name: str):
        assert name.lower() == "acme"
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    await _publish(bus, store, _domain("acme.fr"))

    orgs = store.by_type("organization")
    assert len(orgs) == 1
    org = orgs[0]
    assert org.value == "Acme France SARL"
    assert org.registration_number == "123456789"
    assert org.jurisdiction == "FR"
    assert org.active is True
    assert org.created_at == "2015-06-12"

    # Two human directors emitted, the moral-person one skipped.
    people = store.by_type("person")
    names = {p.value for p in people}
    assert names == {"Marie Dupont", "Jean-Pierre Durand"}

    # Head office location
    locs = store.by_type("location")
    assert any("PARIS" in loc.value for loc in locs)

    # Edges: operates_domain + headquartered_at + 2 × direct_of
    predicates = {r.predicate for r in store.relationships}
    assert {"operates_domain", "headquartered_at", "direct_of"}.issubset(predicates)
    direct_edges = [r for r in store.relationships if r.predicate == "direct_of"]
    assert len(direct_edges) == 2


# ---------------------------------------------------------------------------
# Filtering & skipping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_non_french_tld(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    called = False

    async def fake_search(self, name: str):
        nonlocal called
        called = True
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    await _publish(bus, store, _domain("acme.com"))
    assert called is False
    assert store.by_type("organization") == []


@pytest.mark.asyncio
async def test_skips_public_mail_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    called = False

    async def fake_search(self, name: str):
        nonlocal called
        called = True
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    email = Email(
        value="alice@gmail.com",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, email)
    assert called is False


@pytest.mark.asyncio
async def test_skips_disposable_flagged_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    called = False

    async def fake_search(self, name: str):
        nonlocal called
        called = True
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    d = Domain(
        value="temp.fr",
        metadata={"disposable": True},
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, d)
    assert called is False


@pytest.mark.asyncio
async def test_low_overlap_rejects_false_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API may return a loosely-related result for obscure names. Reject it."""
    bus, store = await _wire()

    async def fake_search(self, name: str):
        return SAMPLE_UNRELATED["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    await _publish(bus, store, _domain("acme.fr"))
    assert store.by_type("organization") == []


@pytest.mark.asyncio
async def test_no_results_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    bus, store = await _wire()

    async def fake_search(self, name: str):
        return None

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)
    await _publish(bus, store, _domain("ghostco.fr"))
    assert store.by_type("organization") == []


@pytest.mark.asyncio
async def test_email_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Email with a French corporate domain triggers the lookup too."""
    bus, store = await _wire()

    seen = {}

    async def fake_search(self, name: str):
        seen["q"] = name
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    email = Email(
        value="contact@acme.fr",
        evidence=[Evidence(collector="test", confidence=1.0)],
    )
    await _publish(bus, store, email)
    assert seen.get("q") == "acme"
    assert store.by_type("organization")
    # But since triggered by an Email, no operates_domain edge (we avoid
    # fabricating a Domain id that isn't in the graph).
    assert not any(r.predicate == "operates_domain" for r in store.relationships)


@pytest.mark.asyncio
async def test_same_domain_not_queried_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus, store = await _wire()

    calls = 0

    async def fake_search(self, name: str):
        nonlocal calls
        calls += 1
        return SAMPLE_ACME["results"][0]

    monkeypatch.setattr(FrenchCompanyLookupCollector, "_search", fake_search)

    await _publish(bus, store, _domain("acme.fr"))
    # Re-publish: the in-session cache must short-circuit.
    await _publish(bus, store, _domain("acme.fr"))
    assert calls == 1


# ---------------------------------------------------------------------------
# Unit-level helpers
# ---------------------------------------------------------------------------


def test_extract_company_hint_strips_www() -> None:
    f = FrenchCompanyLookupCollector._extract_company_hint
    assert f("acme.fr") == "acme"
    assert f("www.acme.fr") == "acme"
    assert f("shop.acme-corp.fr") == "acme corp"
    # Bare TLD without SLD yields ""
    assert f("fr") == ""


def test_name_overlap_metric() -> None:
    f = FrenchCompanyLookupCollector._name_overlap
    assert f("acme", "ACME FRANCE SARL") == 1.0
    assert f("acme corp", "acme consulting") == 0.5
    assert f("totally different", "UNRELATED COMPANY TOTALLY") == 0.5
    assert f("", "anything") == 0.0
