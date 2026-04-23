"""Subdomain extractor from Certificate Transparency logs.

Consumes: Domain entities (previously enriched by DomainLookupCollector)
Produces: Domain entities, subdomain_of relationships

DomainLookupCollector already fetches Certificate Transparency data from
crt.sh and stashes it under `domain.metadata["certificates"]`. Left as-is,
that data only shows up in the graph as an opaque dict attached to one node.
This collector walks it, extracts every distinct subdomain, emits each as
a first-class Domain entity, and adds a `subdomain_of` edge back to the
parent. That makes the attack surface legible on the toile.

Ethics: CT logs are public by design (legally mandated for any modern
CA-issued certificate). Consuming them is exactly what they're for.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.graph import Relationship
from osint_core.entities.identifiers import Domain

log = logging.getLogger(__name__)


class SubdomainExtractor(BaseCollector):
    """Promote CT-log subdomains to first-class graph nodes."""

    name = "subdomain_extractor"
    consumes: ClassVar[list[str]] = ["domain"]
    produces: ClassVar[list[str]] = ["domain"]
    # React to updates — DomainLookupCollector re-populates the metadata
    # after the initial emission.
    dedup: ClassVar[bool] = False

    # Skip wildcards and values that clearly aren't domains.
    _INVALID_FRAGMENTS = ("*", "?", " ", ",")

    async def collect(self, event: EntityDiscovered) -> None:
        parent = event.entity
        if not isinstance(parent, Domain):
            return
        # Avoid processing the same parent's metadata twice.
        if parent.metadata.get("_subdomains_emitted"):
            return
        certificates = parent.metadata.get("certificates") or []
        if not certificates:
            return

        parent_name = parent.value
        parent_suffix = "." + parent_name

        seen: set[str] = set()
        for cert in certificates:
            cn = (cert.get("common_name") or "").strip().lower()
            if not cn:
                continue
            # Handle multi-line SANs occasionally shipped in common_name.
            for candidate in cn.replace(",", "\n").splitlines():
                candidate = candidate.strip().strip(".")
                if not candidate or any(
                    frag in candidate for frag in self._INVALID_FRAGMENTS
                ):
                    continue
                if candidate == parent_name:
                    continue
                if not candidate.endswith(parent_suffix):
                    # CT queries for "*.foo.com" can surface unrelated domains
                    # (e.g., via hosted cert bundles). Ignore.
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)

        if not seen:
            return

        self.log.info(
            "subdomain_extractor: promoting %d subdomain(s) of %s",
            len(seen),
            parent_name,
        )
        parent.metadata["_subdomains_emitted"] = True

        for sub in sorted(seen):
            try:
                subdomain = Domain(
                    value=sub,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=f"https://crt.sh/?q=%.{parent_name}",
                            confidence=0.80,
                            notes=(
                                f"Observed in Certificate Transparency logs "
                                f"for {parent_name}"
                            ),
                            raw_data={"parent_domain": parent_name},
                        )
                    ],
                    metadata={"parent_domain": parent_name},
                )
            except ValueError:
                self.log.debug(
                    "subdomain_extractor: rejected invalid subdomain %r", sub
                )
                continue
            await self.emit(subdomain, event)

            self.emit_relationship(
                Relationship(
                    source_id=subdomain.id,
                    target_id=parent.id,
                    predicate="subdomain_of",
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.95,
                            notes=(
                                f"CT logs show '{sub}' as a subdomain of "
                                f"'{parent_name}'"
                            ),
                        )
                    ],
                )
            )
