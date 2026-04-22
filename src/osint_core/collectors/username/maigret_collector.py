"""Maigret-powered username enumeration.

Wraps the `maigret` library (https://github.com/soxoj/maigret) as an OSINT
collector in our architecture. Maigret checks 3000+ sites for username
existence — far more than Sherlock and more actively maintained.

Install:
    pip install osint-core[maigret]

The Maigret API has evolved across versions. This wrapper tries the most
stable entry points and logs clearly if the installed version is incompatible.
"""

from __future__ import annotations

import logging
from typing import Any

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


class MaigretCollector(BaseCollector):
    """Username enumeration via Maigret.

    Parameters
    ----------
    top_sites : int
        Only check the top-N sites by popularity. 500 is a good default;
        3000+ will give maximum coverage but takes several minutes.
    timeout : int
        Per-site HTTP timeout in seconds.
    """

    name = "maigret"
    consumes = ["username"]
    produces = ["account"]

    def __init__(self, bus, top_sites: int = 500, timeout: int = 30) -> None:
        super().__init__(bus)
        self.top_sites = top_sites
        self.timeout = timeout

    async def collect(self, event: EntityDiscovered) -> None:
        try:
            from maigret.maigret import search as maigret_search
            from maigret.resources import default_db_path
            from maigret.sites import MaigretDatabase
        except ImportError:
            self.log.error(
                "maigret not installed. Run: pip install 'osint-core[maigret]'"
            )
            return

        username = event.entity.value
        self.log.info(
            "maigret searching '%s' across top %d sites (timeout=%ds)",
            username,
            self.top_sites,
            self.timeout,
        )

        try:
            db = MaigretDatabase().load_from_path(default_db_path())
            sites = db.ranked_sites_dict(top=self.top_sites)
        except Exception:
            self.log.exception("failed to load Maigret site database")
            return

        try:
            results: dict[str, Any] = await maigret_search(
                username=username,
                site_dict=sites,
                timeout=self.timeout,
                logger=self.log,
                id_type="username",
                forced=False,
                no_progressbar=True,
            )
        except Exception:
            self.log.exception("maigret search failed for %s", username)
            return

        found_count = 0
        for site_name, result in results.items():
            if not self._is_found(result):
                continue
            found_count += 1
            profile_url = self._extract_url(result, site_name, username)
            extras = self._extract_extras(result)

            account = Account(
                value=f"{site_name.lower()}:{username.lower()}",
                platform=site_name,
                username=username,
                profile_url=profile_url,
                display_name=extras.get("fullname"),
                bio=extras.get("bio"),
                avatar_url=extras.get("avatar_url"),
                evidence=[
                    Evidence(
                        collector=self.name,
                        source_url=profile_url,
                        confidence=0.85,
                        raw_data={"site": site_name, "extras": extras},
                    )
                ],
            )
            await self.emit(account, event)

        self.log.info("maigret found %d accounts for '%s'", found_count, username)

    @staticmethod
    def _is_found(result: Any) -> bool:
        """Resilient check: different Maigret versions expose different fields."""
        status = getattr(result, "status", None)
        if status is None:
            return False
        # Recent versions: status.is_found() / QueryStatus.CLAIMED
        if hasattr(status, "is_found"):
            try:
                return bool(status.is_found())
            except Exception:
                pass
        return str(status).upper().endswith("CLAIMED")

    @staticmethod
    def _extract_url(result: Any, site_name: str, username: str) -> str | None:
        for attr in ("site_url_user", "url"):
            url = getattr(result, attr, None)
            if url:
                return url
        site = getattr(result, "site", None)
        if site is not None:
            tmpl = getattr(site, "url", None)
            if tmpl and "{username}" in tmpl:
                return tmpl.format(username=username)
        return None

    @staticmethod
    def _extract_extras(result: Any) -> dict[str, Any]:
        ids = getattr(result, "ids_data", None) or {}
        return {
            "fullname": ids.get("fullname") or ids.get("name"),
            "bio": ids.get("bio") or ids.get("description"),
            "avatar_url": ids.get("image") or ids.get("avatar"),
            "location": ids.get("location"),
        }
