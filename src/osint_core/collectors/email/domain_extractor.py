"""Extract a Domain entity from every Email, flag disposable providers.

This is a pure in-memory transformation — no network. It exists to:
  1. Materialize the domain part of an email as a first-class entity
     (enables future collectors to do whois, MX lookup, DNS history…).
  2. Surface disposable / forwarder providers early. Investigation
     accuracy drops when the target uses 10MinuteMail — flagging this
     lets humans weight the evidence appropriately.
"""

from __future__ import annotations

from typing import ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.collectors.email.disposable_domains import DISPOSABLE_DOMAINS
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, Email


class EmailDomainExtractor(BaseCollector):
    name = "email_domain"
    consumes: ClassVar[list[str]] = ["email"]
    produces: ClassVar[list[str]] = ["domain"]

    def __init__(
        self,
        bus,
        relationship_sink=None,
        disposable_domains: frozenset[str] | set[str] | None = None,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.disposable_domains = (
            frozenset(disposable_domains)
            if disposable_domains is not None
            else DISPOSABLE_DOMAINS
        )

    async def collect(self, event: EntityDiscovered) -> None:
        email = event.entity
        if not isinstance(email, Email):
            return

        domain_name = email.domain_part
        is_disposable = domain_name in self.disposable_domains

        try:
            domain = Domain(
                value=domain_name,
                metadata={
                    "disposable": is_disposable,
                    "source_emails": [email.value],
                },
                evidence=[
                    Evidence(
                        collector=self.name,
                        confidence=1.0,
                        notes=(
                            f"Domain extracted from {email.value}"
                            + (" (disposable provider)" if is_disposable else "")
                        ),
                        raw_data={"disposable": is_disposable},
                    )
                ],
            )
        except ValueError as exc:
            self.log.debug("domain validation failed for %s: %s", domain_name, exc)
            return

        await self.emit(domain, event)
