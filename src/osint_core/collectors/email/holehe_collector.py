"""Holehe-powered email → registered accounts discovery.

Wraps the holehe library (https://github.com/megadose/holehe) which checks
120+ websites for whether a given email has an account, by probing each
site's password-reset / forgot-password flow and observing the response.

⚠️  OPERATIONAL CAUTION

This collector sends real HTTP requests to ~120 production services, each
of them containing the target email address. Side effects include:

  * Rate limits or soft-bans from the probed services if run repeatedly.
  * In rare cases, some services may send the user an email saying
    "someone tried to reset your password" — harmless, but noisy.
  * Some jurisdictions may treat this as an unauthorized probe. For
    anything beyond self-inspection or authorized investigations (e.g.
    TraceLabs CTFs), ensure you have consent or legitimate basis.

Install:
    pip install 'osint-core[email-lookup]'

Design note: holehe's native API is async (trio) but compatible with
asyncio via httpx. We import modules lazily and call them with our own
httpx.AsyncClient so we can add timeouts and our User-Agent.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Email
from osint_core.entities.profiles import Account


class HoleheCollector(BaseCollector):
    name = "holehe"
    consumes: ClassVar[list[str]] = ["email"]
    produces: ClassVar[list[str]] = ["account"]

    def __init__(
        self,
        bus,
        relationship_sink=None,
        concurrency: int = 10,
        timeout: float = 20.0,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.concurrency = concurrency
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        email = event.entity
        if not isinstance(email, Email):
            return
        address = email.value

        try:
            import httpx
            from holehe.core import import_submodules
        except ImportError:
            self.log.error(
                "holehe not installed. Run: pip install 'osint-core[email-lookup]'"
            )
            return

        try:
            modules = import_submodules("holehe.modules")
        except Exception:
            self.log.exception("failed to enumerate holehe modules")
            return

        functions: list[tuple[str, Any]] = []
        for module_path, module in modules.items():
            func_name = module_path.rsplit(".", 1)[-1]
            func = getattr(module, func_name, None)
            if callable(func):
                functions.append((func_name, func))

        self.log.info(
            "holehe: probing %d services for %s", len(functions), address
        )

        sem = asyncio.Semaphore(self.concurrency)
        results: list[dict[str, Any]] = []

        async def check_one(name: str, func: Any, client: Any) -> None:
            async with sem:
                out: list[dict[str, Any]] = []
                try:
                    await asyncio.wait_for(
                        func(address, client, out), timeout=self.timeout
                    )
                except asyncio.TimeoutError:
                    self.log.debug("holehe %s timed out", name)
                    return
                except Exception as exc:
                    self.log.debug("holehe %s raised %s", name, exc)
                    return
                for entry in out:
                    if entry.get("exists") is True:
                        results.append(entry)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": "osint-core/0.1 (holehe)"},
        ) as client:
            await asyncio.gather(*[check_one(n, f, client) for n, f in functions])

        self.log.info("holehe: %d services registered for %s", len(results), address)

        for entry in results:
            platform = entry.get("name") or entry.get("domain") or "unknown"
            account = Account(
                # We don't know the on-platform username — the dedup_key
                # is <platform>:<email> so this is distinct from any Maigret
                # finding (which uses <platform>:<username>). If both paths
                # find the same account, the correlation engine (future
                # phase) will link them via avatar or stylometry.
                value=f"{platform.lower()}:{address}",
                platform=platform,
                username=address,  # best we have — the email is the registration key
                evidence=[
                    Evidence(
                        collector=self.name,
                        confidence=0.72,  # holehe can false-positive on broken modules
                        notes=(
                            f"Email {address} registered on {platform} "
                            "(on-platform username unknown; confirmed via password-reset probe)"
                        ),
                        raw_data=entry,
                    )
                ],
                metadata={"discovery": "password_reset_probe"},
            )
            await self.emit(account, event)
