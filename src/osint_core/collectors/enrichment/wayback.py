"""Wayback Machine (Internet Archive) snapshot collector.

Consumes: Account entities
Produces: Url entities (one per historical snapshot of interest)

For every Account we've discovered, we query the Internet Archive's public
CDX Server API to find prior captures of that profile URL. The capture
index is free, key-less, and documented at:

    https://archive.org/developers/wayback-cdx-server.html

Why this matters in OSINT
-------------------------
Profiles get edited, renamed, or scrubbed. Wayback lets us recover:
  * Old usernames / display names the account used before a rename
  * Bio / location info that was deleted
  * Old avatar URLs that didn't match current
  * Proof that an account existed at a given date

We emit at most three snapshots per profile URL — the earliest capture,
the latest, and one mid-range — with timestamp metadata. Downstream, the
user can open any of them in their browser.

Ethics / OPSEC
--------------
Wayback is a read-only archive designed for exactly this use case. The
CDX endpoint is anonymous. We don't trigger new crawls (`Save Page Now`
is the separate `save` endpoint — we never call it).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Url
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


class WaybackCollector(BaseCollector):
    """Expose historical snapshots of a profile URL as Url entities."""

    name = "wayback"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["url"]

    # CDX server endpoint. `output=json` returns a list-of-lists with a
    # header row as the first element.
    CDX_URL: ClassVar[str] = "https://web.archive.org/cdx/search/cdx"

    # Cap per-account snapshots we keep in the graph. Wayback sometimes has
    # hundreds of captures for popular profiles — that clutters the toile
    # without adding unique signal.
    MAX_SNAPSHOTS_PER_ACCOUNT: ClassVar[int] = 3

    def __init__(
        self,
        bus,
        relationship_sink=None,
        timeout: float = 15.0,
        limit: int = 20,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout
        # Upper bound for the CDX query. We'll still slice to
        # MAX_SNAPSHOTS_PER_ACCOUNT before emitting.
        self.limit = limit

    async def collect(self, event: EntityDiscovered) -> None:
        account = event.entity
        if not isinstance(account, Account):
            return
        url = account.profile_url
        if not url:
            return

        snapshots = await self._fetch_snapshots(url)
        if not snapshots:
            self.log.debug("wayback: no snapshots for %s", url)
            return

        chosen = self._pick_representative(snapshots)
        self.log.info(
            "wayback: %s has %d snapshot(s); emitting %d",
            url, len(snapshots), len(chosen),
        )

        for snap in chosen:
            archive_url = self._build_archive_url(snap)
            try:
                archived = Url(
                    value=archive_url,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            source_url=archive_url,
                            confidence=0.95,
                            notes=(
                                f"Wayback snapshot of {url} from "
                                f"{self._pretty_timestamp(snap['timestamp'])} "
                                f"(HTTP {snap.get('statuscode', '?')})"
                            ),
                            raw_data={
                                "wayback_timestamp": snap["timestamp"],
                                "original": snap["original"],
                                "statuscode": snap.get("statuscode"),
                                "mimetype": snap.get("mimetype"),
                            },
                        )
                    ],
                    metadata={
                        "archive_of": url,
                        "wayback_timestamp": snap["timestamp"],
                    },
                )
            except ValueError:
                continue
            await self.emit(archived, event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_snapshots(self, url: str) -> list[dict[str, Any]]:
        """Query CDX for snapshots of `url`.

        Returns a list of dicts with at least `timestamp` and `original`.
        The CDX API returns a JSON list-of-lists; the first row is a header.
        """
        params = {
            "url": url,
            "output": "json",
            "limit": str(self.limit),
            # Collapse consecutive captures of the same digest — we don't
            # want 50 identical snapshots cluttering the graph.
            "collapse": "digest",
            # Only 2xx/3xx captures — a wall of 404s adds noise.
            "filter": "statuscode:[23]..",
            # Fields we care about. Keep this tight for bandwidth.
            "fl": "timestamp,original,statuscode,mimetype,digest",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                r = await client.get(
                    self.CDX_URL,
                    params=params,
                    headers={"User-Agent": "osint-core/0.1 (research)"},
                )
        except httpx.HTTPError as exc:
            self.log.warning("wayback: network error on %s: %s", url, exc)
            return []

        if r.status_code != 200:
            self.log.info(
                "wayback: CDX returned %d for %s", r.status_code, url
            )
            return []
        try:
            rows = r.json()
        except ValueError:
            return []

        # CDX JSON: first row is header, rest are data.
        if not isinstance(rows, list) or len(rows) < 2:
            return []
        header = rows[0]
        snapshots: list[dict[str, Any]] = []
        for row in rows[1:]:
            if not isinstance(row, list):
                continue
            snapshots.append(dict(zip(header, row)))
        return snapshots

    def _pick_representative(
        self, snapshots: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Pick earliest, latest, and median (when available).

        Wayback's CDX returns rows in ascending time order, so we just pick
        by index without re-sorting.
        """
        n = len(snapshots)
        if n <= self.MAX_SNAPSHOTS_PER_ACCOUNT:
            return snapshots
        # earliest, middle, latest — preserves chronology in the graph.
        picks = [snapshots[0], snapshots[n // 2], snapshots[-1]]
        # Dedup in case n is very small or rows collide.
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in picks:
            k = f"{p.get('timestamp')}@{p.get('digest')}"
            if k in seen:
                continue
            seen.add(k)
            unique.append(p)
        return unique

    @staticmethod
    def _build_archive_url(snap: dict[str, Any]) -> str:
        """Build the Wayback viewer URL for a given snapshot row."""
        ts = snap.get("timestamp", "")
        original = snap.get("original", "")
        return f"https://web.archive.org/web/{ts}/{original}"

    @staticmethod
    def _pretty_timestamp(ts: str) -> str:
        """CDX timestamps are `YYYYMMDDhhmmss`. Format as a human-ish string."""
        if not ts or len(ts) < 8:
            return ts or "?"
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


__all__ = ["WaybackCollector"]
