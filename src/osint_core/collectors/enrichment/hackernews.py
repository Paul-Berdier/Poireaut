"""HackerNews public profile collector.

Consumes: Account entities where platform == "hackernews"
Produces: email/url/location entities extracted from the `about` field.

HN exposes public user data via Firebase:
    https://hacker-news.firebaseio.com/v0/user/{id}.json

Returned JSON:
    {
        "id": "pg",
        "created": 1160418092,         # unix ts
        "karma": 155111,
        "about": "Founded Y Combinator. Before that Viaweb..."
    }

We upgrade the Account with karma/creation date and run the same suite of
text extractors used for bios on the `about` field.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.collectors.enrichment.extractors import DEFAULT_EXTRACTORS, Extractor
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


class HackerNewsCollector(BaseCollector):
    """Enrich a HackerNews Account with profile metadata + bio extraction."""

    name = "hackernews"
    consumes: ClassVar[list[str]] = ["account"]
    produces: ClassVar[list[str]] = ["email", "url", "location", "username"]

    def __init__(
        self,
        bus,
        relationship_sink=None,
        extractors: list[Extractor] | None = None,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.timeout = timeout
        # Reuse the default bio extractors — same signals apply.
        self.extractors = extractors if extractors is not None else list(DEFAULT_EXTRACTORS)

    async def collect(self, event: EntityDiscovered) -> None:
        account = event.entity
        if not isinstance(account, Account):
            return
        if (account.platform or "").lower() != "hackernews":
            return
        username = account.username
        if not username:
            return

        data = await self._fetch(username)
        if not data:
            return

        about = str(data.get("about") or "")
        karma = data.get("karma")
        created_ts = data.get("created")
        created_iso: str | None = None
        if isinstance(created_ts, (int, float)):
            try:
                created_iso = (
                    datetime.fromtimestamp(int(created_ts), tz=timezone.utc).isoformat()
                )
            except (OverflowError, OSError, ValueError):
                created_iso = None

        # 1) Upgrade the account with enriched data (store's merge will fill
        #    in any None fields on the original).
        upgraded = Account(
            value=account.value,
            platform=account.platform,
            username=account.username,
            profile_url=account.profile_url
            or f"https://news.ycombinator.com/user?id={username}",
            display_name=account.display_name,
            bio=self._strip_tags(about) or None,
            followers_count=None,
            evidence=[
                Evidence(
                    collector=self.name,
                    source_url=f"https://hacker-news.firebaseio.com/v0/user/{username}.json",
                    confidence=0.95,
                    notes=f"HackerNews public profile (karma={karma})",
                    raw_data={
                        "karma": karma,
                        "created_at": created_iso,
                    },
                )
            ],
            metadata={
                "enriched": True,
                "hn_karma": karma,
                "hn_created_at": created_iso,
            },
        )
        await self.emit(upgraded, event)

        # 2) Run bio extractors against the `about` text (stripped of HTML).
        clean = self._strip_tags(about)
        if not clean:
            return
        context = {
            "profile_url": f"https://news.ycombinator.com/user?id={username}",
            "platform": "hackernews",
            "username": username,
            "account_id": str(account.id),
        }
        emitted = 0
        for extractor in self.extractors:
            for entity, confidence in extractor.extract(clean, context):
                entity.evidence.append(
                    Evidence(
                        collector=self.name,
                        source_url=context["profile_url"],
                        confidence=confidence,
                        notes=(
                            f"extracted by {extractor.name} "
                            f"from HN bio of @{username}"
                        ),
                        raw_data={"extractor": extractor.name},
                    )
                )
                await self.emit(entity, event)
                emitted += 1
        self.log.info(
            "hackernews: enriched %s (karma=%s, %d sub-entities)",
            username, karma, emitted,
        )

    @staticmethod
    def _strip_tags(html: str) -> str:
        """Turn HN's lightly-HTML-escaped `about` text into plain text.

        HN renders URLs as `<a href="https://x.dev" rel="nofollow">...</a>`.
        A naive tag-stripper would discard the href attribute, losing the URL
        when the link text is something like "blog" instead of the raw URL.
        We pre-extract `href="..."` values and append them to the output so
        the downstream URL extractor still sees them.
        """
        import re

        # 1) Harvest href values before we destroy the tags.
        hrefs = re.findall(
            r'<a\s+[^>]*href\s*=\s*["\']([^"\']+)["\']', html, flags=re.IGNORECASE
        )

        # 2) Strip tags — replace with a single space, then collapse whitespace.
        no_tags = re.sub(r"<[^>]+>", " ", html)
        # Decode a handful of common entities — no need for full html.unescape
        no_tags = (
            no_tags.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#x27;", "'")
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
        )
        text = " ".join(no_tags.split()).strip()

        # 3) Re-append any hrefs that didn't already appear verbatim in the text.
        for href in hrefs:
            # Only promote real http(s) and mailto: URLs back into the bio.
            # HN rewrites bare domains to https URLs, so the protocol is expected.
            if not (href.startswith("http://") or href.startswith("https://")
                    or href.startswith("mailto:")):
                continue
            if href in text:
                continue
            text = f"{text} {href}" if text else href

        return text

    async def _fetch(self, username: str) -> dict[str, Any] | None:
        url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    url,
                    headers={"User-Agent": "osint-core/0.1 (research)"},
                )
        except httpx.HTTPError as exc:
            self.log.warning("hackernews: network error for %s: %s", username, exc)
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        # HN returns `null` (valid JSON) for unknown users.
        if not isinstance(data, dict):
            return None
        return data
