"""urlscan.io lookup collector.

Consumes: Url entities
Produces: Domain, IpAddress, Location entities

urlscan.io (https://urlscan.io) indexes millions of URL scans and exposes
an anonymous search API (`/api/v1/search/`). For any URL we've already
discovered, we ask urlscan for existing scans of that same URL — which
gives us the resolved IP, primary domain, server country, redirect
chain, and the screenshot permalink.

Unlike `scan` (which submits a new scan and requires a registered API
key), the **search** endpoint is open and doesn't need a key. Results
are limited to what other investigators have already submitted — which
for popular URLs is plenty.

Ethics / OPSEC
--------------
Search is a read-only query against urlscan's public index. The target
URL is NOT re-crawled. This means:
  * No new HTTP hit lands on the target from urlscan because of us
  * No trace for the URL owner that anyone looked them up
  * We only see data others already published

We keep the emission conservative — one Domain, one IpAddress, and one
Location per resolved URL — so the graph stays legible.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, IpAddress, Url
from osint_core.entities.profiles import Location

log = logging.getLogger(__name__)


class UrlscanCollector(BaseCollector):
    """Resolve a URL to its IP/domain/country via urlscan.io's public search."""

    name = "urlscan"
    consumes: ClassVar[list[str]] = ["url"]
    produces: ClassVar[list[str]] = ["domain", "ip", "location"]

    SEARCH_URL: ClassVar[str] = "https://urlscan.io/api/v1/search/"

    # Skip URLs pointing at infrastructure we already have in the graph —
    # no point asking urlscan about github.com or our own wayback emissions.
    _NOISE_HOSTS: ClassVar[frozenset[str]] = frozenset({
        "github.com", "gitlab.com", "twitter.com", "x.com",
        "keybase.io", "news.ycombinator.com", "gravatar.com",
        "web.archive.org", "archive.org",
        "youtube.com", "youtu.be", "google.com",
    })

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 15.0,
        results_per_url: int = 1,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout
        self.results_per_url = results_per_url

    async def collect(self, event: EntityDiscovered) -> None:
        url_entity = event.entity
        if not isinstance(url_entity, Url):
            return
        url = url_entity.value

        host = self._host_of(url)
        if host and host.lower() in self._NOISE_HOSTS:
            self.log.debug("urlscan: skipping well-known host %s", host)
            return

        result = await self._search_one(url)
        if not result:
            return

        page = result.get("page") or {}
        domain = (page.get("domain") or "").lower()
        ip = page.get("ip") or ""
        country = page.get("country") or ""
        server = page.get("server") or ""
        scan_url = result.get("result") or ""  # permalink to the urlscan report
        screenshot = result.get("screenshot") or ""

        self.log.info(
            "urlscan: %s resolved to domain=%s ip=%s country=%s",
            url, domain or "?", ip or "?", country or "?",
        )

        # Enrich the original Url entity with the urlscan metadata.
        url_entity.metadata.update({
            "urlscan_report": scan_url,
            "urlscan_screenshot": screenshot,
            "urlscan_server_header": server,
        })

        if domain:
            try:
                d = Domain(
                    value=domain,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=scan_url or url,
                            confidence=0.90,
                            notes=f"Resolved domain for {url} via urlscan.io",
                            raw_data={"page": page, "scan_permalink": scan_url},
                        )
                    ],
                    metadata={"server_header": server},
                )
                await self.emit(d, event)
            except ValueError:
                pass

        if ip:
            try:
                ip_entity = IpAddress(
                    value=ip,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=scan_url or url,
                            confidence=0.90,
                            notes=f"Server IP of {url} per urlscan.io",
                            raw_data={"scan_permalink": scan_url},
                        )
                    ],
                )
                await self.emit(ip_entity, event)
            except ValueError:
                self.log.debug("urlscan: rejected malformed IP %r", ip)

        if country:
            try:
                loc = Location(
                    value=country,
                    country=country,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=scan_url or url,
                            # Country-level only — low precision, moderate confidence.
                            confidence=0.55,
                            notes=(
                                f"Hosting country for {url} per urlscan.io "
                                f"(server-level geolocation, not user location)"
                            ),
                        )
                    ],
                )
                await self.emit(loc, event)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _search_one(self, url: str) -> dict[str, Any] | None:
        """Return the best match from urlscan search for `url`, or None."""
        # `domain:` keyword narrows down noise when the URL has a long path.
        host = self._host_of(url) or url
        params = {
            "q": f'domain:{host}',
            "size": str(self.results_per_url),
        }
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
            self.log.warning("urlscan: network error on %s: %s", url, exc)
            return None

        if r.status_code == 429:
            self.log.warning(
                "urlscan: rate-limited (429). "
                "Free tier is 500/day anonymous — consider an API key."
            )
            return None
        if r.status_code != 200:
            self.log.info("urlscan: HTTP %d for %s", r.status_code, url)
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        results = data.get("results") or []
        if not results:
            return None
        # Return the most recent result — urlscan orders newest first by default.
        return results[0]

    @staticmethod
    def _host_of(url: str) -> str:
        """Tiny stdlib-only host extractor — avoids pulling in urllib's full parse."""
        s = url.strip()
        for prefix in ("https://", "http://"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        # Drop port, path, query.
        for sep in ("/", "?", "#"):
            idx = s.find(sep)
            if idx != -1:
                s = s[:idx]
        if ":" in s:
            s = s.split(":", 1)[0]
        return s.lower()


__all__ = ["UrlscanCollector"]
