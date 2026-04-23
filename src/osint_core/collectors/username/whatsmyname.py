"""WhatsMyName-driven username enumeration.

Consumes: Username entities
Produces: Account entities

The WhatsMyName project (https://github.com/WebBreacher/WhatsMyName) maintains
a community-curated JSON file describing how to reliably check whether a
given username exists on ~600 websites. Each site entry carries two kinds
of signal:

  e_code + e_string   → HTTP status + response-body substring expected
                        when the account EXISTS.
  m_code + m_string   → the equivalent pair for when the account DOES NOT
                        exist.

A site is counted as a hit only when the `e_` signals match AND the `m_`
signals explicitly don't — this dual check collapses the false-positive
rate to near-zero, which is the whole reason WMN exists (most username
checkers flag any 200 OK as "found").

Data file handling
------------------
We ship a compact fallback in `wmn-data.json` (≈18 high-confidence sites)
so the collector works immediately after `pip install`. For the full 600+
site catalog, users run:

    osint update-wmn     # or: poireaut update-wmn

which downloads the latest file from WebBreacher/WhatsMyName into the
user's cache directory (`~/.cache/osint-core/wmn-data.json`). The
collector prefers the cached copy when present, falling back to the
bundled subset otherwise.

Ethics / OPSEC
--------------
This is the same category of probe as our existing HttpUsernameCollector:
a single GET (or POST with the provided body) to the profile URL, using
the standard username placeholder. No authentication is attempted, no
session is opened, no write. The target site receives one anonymous
HTTP hit per check. We honor rate-limiting by capping concurrency.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import Any, ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.profiles import Account

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _default_cache_path() -> Path:
    """User-level cache path honoring XDG_CACHE_HOME where applicable."""
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "osint-core" / "wmn-data.json"


def _read_bundled_wmn() -> dict[str, Any]:
    """Load the compact fallback shipped inside the package."""
    text = (
        resources.files("osint_core.collectors.username")
        .joinpath("wmn-data.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def load_wmn_data(
    cache_path: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return `(sites_list, source_label)`.

    Prefers a cached full database if it exists under the user cache,
    otherwise falls back to the bundled subset. The source label is
    logged so operators know which catalog was used.
    """
    path = cache_path if cache_path is not None else _default_cache_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sites = data.get("sites") or []
            if isinstance(sites, list) and sites:
                return sites, f"cache:{path}"
        except (OSError, ValueError) as exc:
            log.warning("wmn: cached file unreadable (%s); using bundled", exc)
    bundled = _read_bundled_wmn()
    return bundled.get("sites", []), "bundled"


async def fetch_and_cache_wmn(
    cache_path: Path | None = None,
    url: str = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json",
    timeout: float = 30.0,
) -> Path:
    """Download the authoritative wmn-data.json into the user's cache.

    Returns the path written. Raises on failure — callers (the CLI
    `update-wmn` command) surface the error to the user.
    """
    path = cache_path if cache_path is not None else _default_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(
            url,
            headers={"User-Agent": "osint-core/0.1 (research)"},
        )
    r.raise_for_status()

    # Sanity-check: must parse as JSON and contain a `sites` list.
    data = r.json()
    if not isinstance(data.get("sites"), list):
        raise ValueError("wmn: downloaded payload is missing 'sites' list")

    # Atomic write so a partial download doesn't corrupt the cache.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(r.text, encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class WhatsMyNameCollector(BaseCollector):
    """Username enumeration across every site in the WMN catalog."""

    name = "whatsmyname"
    consumes: ClassVar[list[str]] = ["username"]
    produces: ClassVar[list[str]] = ["account"]

    # Categories we skip by default — NSFW/dating surface a lot of accounts
    # with the same pseudonym that are almost always unrelated to the target.
    # Operators can override by passing `skip_categories=frozenset()`.
    _DEFAULT_SKIP_CATEGORIES: ClassVar[frozenset[str]] = frozenset({
        "xx-nsfw-xx", "adult", "dating",
    })

    def __init__(
        self,
        bus,
        relationship_sink=None,
        sites: list[dict[str, Any]] | None = None,
        concurrency: int = 15,
        timeout: float = 8.0,
        skip_categories: frozenset[str] | set[str] | None = None,
        user_agent: str | None = None,
    ) -> None:
        super().__init__(bus, relationship_sink=relationship_sink)
        self.concurrency = concurrency
        self.timeout = timeout
        self.skip_categories = (
            frozenset(skip_categories)
            if skip_categories is not None
            else self._DEFAULT_SKIP_CATEGORIES
        )
        self.user_agent = user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        if sites is not None:
            self._sites = sites
            self._source = "injected"
        else:
            self._sites, self._source = load_wmn_data()

        self.log.info(
            "whatsmyname: loaded %d site(s) from %s",
            len(self._sites), self._source,
        )

    async def collect(self, event: EntityDiscovered) -> None:
        username = event.entity.value
        sem = asyncio.Semaphore(self.concurrency)
        found: list[tuple[dict[str, Any], str]] = []

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/json,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:

            async def probe_one(site: dict[str, Any]) -> None:
                if self._should_skip(site):
                    return
                url = self._render_url(site.get("uri_check", ""), username)
                if not url:
                    return
                async with sem:
                    hit = await self._check(client, site, username, url)
                if hit:
                    found.append((site, url))

            await asyncio.gather(
                *(probe_one(site) for site in self._sites),
                return_exceptions=True,
            )

        self.log.info(
            "whatsmyname: '%s' found on %d / %d sites",
            username, len(found), len(self._sites),
        )

        for site, url in found:
            name = site.get("name", "unknown")
            pretty_url = self._render_url(site.get("uri_pretty", ""), username) or url
            account = Account(
                value=f"{name.lower()}:{username.lower()}",
                platform=name,
                username=username,
                profile_url=pretty_url,
                evidence=[
                    Evidence(
                        collector=self.name,
                        source_url=url,
                        # WMN's dual-signal check is stricter than our
                        # legacy HTTP checker — bump confidence accordingly.
                        confidence=0.88,
                        notes=(
                            f"WhatsMyName dual-signal match on {name} "
                            f"(category={site.get('cat', 'uncategorized')})"
                        ),
                        raw_data={
                            "wmn_site": name,
                            "wmn_category": site.get("cat"),
                            "wmn_check_url": url,
                        },
                    )
                ],
                metadata={"source": "whatsmyname", "wmn_source": self._source},
            )
            await self.emit(account, event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_skip(self, site: dict[str, Any]) -> bool:
        cat = (site.get("cat") or "").lower()
        return cat in self.skip_categories

    @staticmethod
    def _render_url(template: str, username: str) -> str:
        if not template or "{account}" not in template:
            return template or ""
        return template.replace("{account}", username)

    @staticmethod
    def _body_contains(body: str, needle: str, username: str) -> bool:
        """WMN patterns may embed {account} in e_string / m_string."""
        if not needle:
            return False
        resolved = needle.replace("{account}", username)
        return resolved in body

    async def _check(
        self,
        client: httpx.AsyncClient,
        site: dict[str, Any],
        username: str,
        url: str,
    ) -> bool:
        """Return True iff both existence signals match AND absence signals don't."""
        try:
            post_body = site.get("post_body")
            if post_body:
                # WMN POST probe. The body is sent as-is (fields already
                # formatted with {account}).
                body = post_body.replace("{account}", username)
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                r = await client.post(url, content=body, headers=headers)
            else:
                r = await client.get(url)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.TooManyRedirects):
            return False
        except Exception as exc:
            self.log.debug("wmn: %s probe raised %s", site.get("name"), exc)
            return False

        body = r.text or ""
        e_code = site.get("e_code")
        m_code = site.get("m_code")
        e_string = site.get("e_string") or ""
        m_string = site.get("m_string") or ""

        code_ok = (e_code is None) or (r.status_code == e_code)
        if not code_ok:
            return False

        has_e_string = self._body_contains(body, e_string, username)
        has_m_string = self._body_contains(body, m_string, username)

        # WMN dual-signal rule: require the existence substring AND the
        # absence substring NOT to be there. Sites without one of the
        # two signals fall back to a single-signal check.
        if e_string and m_string:
            return has_e_string and not has_m_string
        if e_string:
            return has_e_string
        if m_string:
            # Existence-by-absence: the response must not contain the
            # "not found" marker and the HTTP code must match e_code.
            return not has_m_string
        # If the site declares neither string, treat a matching e_code alone
        # as a weak positive. These entries are rare and sometimes noisy.
        return code_ok


__all__ = [
    "WhatsMyNameCollector",
    "fetch_and_cache_wmn",
    "load_wmn_data",
    "_default_cache_path",
]
