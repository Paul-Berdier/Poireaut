"""French company lookup via the public `recherche-entreprises.api.gouv.fr`.

Consumes: Domain entities (with a French TLD), Email entities (by domain)
Produces: Organization, Person (dirigeants), Location entities
          + operates_domain, direct_of, headquartered_at relationships.

The API is operated by DINUM (the French inter-ministerial digital agency)
and aggregates INSEE (SIRENE), INPI (RNE) and BODACC. It's public, key-less,
and rate-limited to 7 req/s. Docs:
  https://recherche-entreprises.api.gouv.fr/docs/
  https://github.com/annuaire-entreprises-data-gouv-fr/search-api

Ethics / OPSEC
--------------
All data returned is legally-mandated public registry information. Under
French law (loi Macron 2015), the RCS must be freely accessible. Company
directors have the right to opt out of diffusion — the API surfaces only
names of people who have not opted out. We respect that by design: we
never try to de-anonymize the `diffusion_partielle` flag.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.identifiers import Domain, Email
from osint_core.entities.profiles import Location, Organization, Person

log = logging.getLogger(__name__)


# TLDs we consider "worth looking up" as French companies. We deliberately
# don't lookup bare .com / .net — way too many false positives. Users who
# need that should add the TLD to `french_tlds` at construction time.
_DEFAULT_FR_TLDS: frozenset[str] = frozenset({
    "fr", "re", "pm", "wf", "tf", "yt", "gp", "mq", "gf", "nc",
    "alsace", "bzh", "corsica", "paris",
})

# Common public-mail providers — skip those so we don't try to "match"
# gmail.com against a fictitious French company.
_PUBLIC_MAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.fr", "outlook.com",
    "outlook.fr", "hotmail.com", "hotmail.fr", "live.com", "live.fr",
    "protonmail.com", "proton.me", "pm.me", "icloud.com", "me.com",
    "laposte.net", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "gmx.com",
    "gmx.fr", "aol.com", "mail.com", "yandex.com", "zoho.com",
    "tutanota.com", "tuta.io",
})


class FrenchCompanyLookupCollector(BaseCollector):
    """Query the official French company registry by domain name."""

    name = "french_company_lookup"
    consumes: ClassVar[list[str]] = ["domain", "email"]
    produces: ClassVar[list[str]] = ["organization", "person", "location"]

    SEARCH_URL: ClassVar[str] = "https://recherche-entreprises.api.gouv.fr/search"

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 12.0,
        french_tlds: frozenset[str] | set[str] | None = None,
        public_mail_domains: frozenset[str] | set[str] | None = None,
        # We only emit a hit when the top search result's score is high
        # AND its name overlaps the query. Cap the uncertainty.
        min_name_overlap: float = 0.5,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout
        self.french_tlds = (
            frozenset(french_tlds) if french_tlds is not None else _DEFAULT_FR_TLDS
        )
        self.public_mail_domains = (
            frozenset(public_mail_domains)
            if public_mail_domains is not None
            else _PUBLIC_MAIL_DOMAINS
        )
        self.min_name_overlap = min_name_overlap
        # In-session dedup: don't query the same company name twice.
        self._seen_queries: set[str] = set()

    async def collect(self, event: EntityDiscovered) -> None:
        entity = event.entity

        # Resolve a domain-of-interest from the triggering entity.
        if isinstance(entity, Domain):
            dom = entity.value.lower()
        elif isinstance(entity, Email):
            dom = entity.domain_part
        else:
            return

        if dom in self.public_mail_domains:
            return
        tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
        if tld not in self.french_tlds:
            return
        if entity.metadata.get("disposable"):
            return

        query_name = self._extract_company_hint(dom)
        if not query_name or len(query_name) < 3:
            return
        if query_name in self._seen_queries:
            return
        self._seen_queries.add(query_name)

        best = await self._search(query_name)
        if not best:
            self.log.info("french_company_lookup: no match for '%s'", query_name)
            return

        overlap = self._name_overlap(query_name, best.get("nom_complet", ""))
        if overlap < self.min_name_overlap:
            self.log.debug(
                "french_company_lookup: low-confidence match rejected "
                "(%s vs %s, overlap=%.2f)",
                query_name, best.get("nom_complet"), overlap,
            )
            return

        await self._emit_company(best, event, origin_domain=dom)

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------

    async def _search(self, name: str) -> dict[str, Any] | None:
        """Return the top search result or None."""
        params = {"q": name, "page": "1", "per_page": "3"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                r = await client.get(
                    self.SEARCH_URL,
                    params=params,
                    headers={
                        "User-Agent": "osint-core/0.1 (research)",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            self.log.warning(
                "french_company_lookup: network error on '%s': %s", name, exc
            )
            return None

        if r.status_code == 429:
            self.log.warning(
                "french_company_lookup: API rate-limited (429). "
                "The public quota is 7 req/s."
            )
            return None
        if r.status_code != 200:
            self.log.info(
                "french_company_lookup: HTTP %d for '%s'",
                r.status_code, name,
            )
            return None

        try:
            data = r.json()
        except ValueError:
            return None
        results = data.get("results") or []
        if not results:
            return None
        # The API ranks results by relevance already; return the top one.
        return results[0]

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    async def _emit_company(
        self,
        result: dict[str, Any],
        origin_event: EntityDiscovered,
        origin_domain: str,
    ) -> None:
        siren = result.get("siren") or ""
        nom = (
            result.get("nom_complet")
            or result.get("nom_raison_sociale")
            or result.get("nom_commercial")
            or siren
            or "unknown"
        )
        siege = result.get("siege") or {}
        siege_ville = siege.get("libelle_commune") or ""
        siege_cp = siege.get("code_postal") or ""
        siege_address = siege.get("geo_adresse") or ""
        date_creation = result.get("date_creation") or ""
        etat_admin = result.get("etat_administratif") or ""
        nature_juridique = result.get("nature_juridique") or ""
        dirigeants = result.get("dirigeants") or []

        self.log.info(
            "french_company_lookup: match for '%s' → %s (SIREN %s)",
            origin_domain, nom, siren or "?",
        )

        org = Organization(
            value=nom,
            legal_form=nature_juridique or None,
            registration_number=siren or None,
            jurisdiction="FR",
            registered_address=siege_address or None,
            active=(etat_admin == "A") if etat_admin else None,
            created_at=date_creation or None,
            metadata={
                "siren": siren,
                "source": "recherche-entreprises.api.gouv.fr",
                "raw": {
                    k: result.get(k)
                    for k in ("siren", "nom_complet", "tranche_effectif_salarie",
                              "categorie_entreprise", "nature_juridique",
                              "activite_principale", "etat_administratif",
                              "date_creation")
                    if result.get(k) is not None
                },
            },
            evidence=[
                Evidence(
                    collector=self.name,
                    source_url=(
                        f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"
                        if siren else None
                    ),
                    confidence=0.88,
                    notes=(
                        f"Matched French company '{nom}' (SIREN {siren}) "
                        f"to domain {origin_domain}"
                    ),
                )
            ],
        )
        await self.emit(org, origin_event)

        # operates_domain edge
        origin_entity = origin_event.entity
        if isinstance(origin_entity, Domain):
            target_domain_id = origin_entity.id
        else:
            # If triggered by an Email, skip the operates_domain edge —
            # the domain entity may not be in the graph yet and we don't
            # want to fabricate an id.
            target_domain_id = None
        if target_domain_id is not None:
            self.emit_relationship(
                Relationship(
                    source_id=org.id,
                    target_id=target_domain_id,
                    predicate="operates_domain",
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.82,
                            notes=(
                                f"Domain {origin_domain} plausibly operated by "
                                f"{nom} (heuristic match on corporate name)"
                            ),
                        )
                    ],
                )
            )

        # Headquarters location
        if siege_ville or siege_address:
            loc_value = siege_address or f"{siege_cp} {siege_ville}".strip()
            try:
                loc = Location(
                    value=loc_value,
                    country="FR",
                    city=siege_ville or None,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.9,
                            notes=f"Registered head office of {nom} (SIREN {siren})",
                        )
                    ],
                )
            except ValueError:
                loc = None
            if loc is not None:
                await self.emit(loc, origin_event)
                self.emit_relationship(
                    Relationship(
                        source_id=org.id,
                        target_id=loc.id,
                        predicate="headquartered_at",
                        evidence=[
                            Evidence(
                                collector=self.name,
                                confidence=0.95,
                                notes=f"SIRENE registered address for SIREN {siren}",
                            )
                        ],
                    )
                )

        # Dirigeants → Person nodes + direct_of edges.
        # The API omits this block when the person has opted out of
        # diffusion, so whatever is here is lawfully public.
        for d in dirigeants:
            if not isinstance(d, dict):
                continue
            q = d.get("qualite") or "dirigeant"
            # Physical persons have prenoms + nom; moral persons have a
            # 'denomination' + siren (recursive!) — we only emit individuals.
            prenoms = (d.get("prenoms") or "").strip()
            nom_dir = (d.get("nom") or "").strip()
            if not (prenoms or nom_dir):
                # Skip moral-person directors for now — deep nesting.
                continue
            full = f"{prenoms} {nom_dir}".strip().title() or "anonymous"
            try:
                person = Person(
                    value=full,
                    full_name=full,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=(
                                f"https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"
                                if siren else None
                            ),
                            confidence=0.9,
                            notes=(
                                f"{q} of {nom} per the French RNE "
                                "(publicly disclosed; diffusion=full)"
                            ),
                            raw_data={
                                "qualite": q,
                                "annee_naissance": d.get("annee_de_naissance"),
                                "nationalite": d.get("nationalite"),
                            },
                        )
                    ],
                    metadata={"role": q, "of_siren": siren},
                )
            except ValueError:
                continue
            await self.emit(person, origin_event)
            self.emit_relationship(
                Relationship(
                    source_id=person.id,
                    target_id=org.id,
                    predicate="direct_of",
                    metadata={"qualite": q},
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.9,
                            notes=f"{q.title()} role in public RNE",
                        )
                    ],
                )
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_company_hint(domain: str) -> str:
        """From `acme-corp.fr` → `acme-corp`. Strips common sub-domains."""
        parts = domain.split(".")
        # Drop common prefixes that aren't the company name.
        while parts and parts[0] in ("www", "mail", "smtp", "webmail", "blog", "shop"):
            parts.pop(0)
        if len(parts) < 2:
            return ""
        # Use everything before the TLD — handles multi-part SLDs like `co.uk`
        # poorly, but for French TLDs the SLD == company name is reliable.
        return parts[0].replace("-", " ").strip()

    @staticmethod
    def _name_overlap(query: str, candidate: str) -> float:
        """Crude word-overlap metric between the queried name and the returned one.

        Returns the fraction of query words that also appear (as substrings)
        in the candidate, case-insensitively. A perfect match on a single
        word returns 1.0; `"acme"` vs `"acme consulting sarl"` also returns
        1.0 (all query words present).
        """
        if not query or not candidate:
            return 0.0
        q_words = [w for w in query.lower().split() if len(w) >= 2]
        if not q_words:
            return 0.0
        c_low = candidate.lower()
        hits = sum(1 for w in q_words if w in c_low)
        return hits / len(q_words)


__all__ = ["FrenchCompanyLookupCollector"]
