"""Profile data fetchers.

When possible, we hit a platform's official public API (GitHub, GitLab)
because it gives richer, structured data with explicit rate limits.
For unknown platforms, we fall back to fetching the HTML page and
extracting OpenGraph / meta description tags — a small regex-based
parser avoids pulling in BeautifulSoup as a core dependency.

Ethics / OPSEC notes:
  * We send a descriptive User-Agent so site owners can identify us.
  * We honor HTTP timeouts to avoid hanging.
  * We do NOT currently check robots.txt — TODO for a production build.
  * We do NOT persist fetched HTML to disk by default.
  * GitHub API works unauthenticated (60 req/hour); supply a PAT via
    GITHUB_TOKEN env var for 5000 req/hour.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)


DEFAULT_USER_AGENT = (
    "osint-core/0.1 (+https://github.com/your-org/osint-core; research)"
)


@dataclass
class FetchResult:
    """Normalized result from any fetcher."""

    status: int  # HTTP status, or 0 on exception
    fetched_url: str
    bio: str = ""  # free-text blob to feed to extractors
    display_name: str | None = None
    avatar_url: str | None = None
    followers: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.bio or self.display_name)


class ProfileFetcher:
    """Fetches and normalizes profile data across platforms."""

    # Registry: platform name (lower) -> method name
    _PLATFORM_HANDLERS: dict[str, str] = {
        "github": "_fetch_github",
        "gitlab": "_fetch_gitlab",
        "gravatar": "_fetch_gravatar",
    }

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
        }
        # Optional: external client for reuse / mocking
        self._external_client = client

    async def fetch(
        self, platform: str, username: str, profile_url: str
    ) -> FetchResult:
        method_name = self._PLATFORM_HANDLERS.get((platform or "").lower())
        if method_name:
            method = getattr(self, method_name)
            try:
                return await method(username)
            except Exception as exc:
                log.warning(
                    "platform fetcher for %s failed: %s — falling back to HTML",
                    platform,
                    exc,
                )
        # Fallback for unsupported platforms or API failure
        return await self._fetch_generic(profile_url)

    async def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Platform-specific fetchers
    # ------------------------------------------------------------------

    async def _fetch_github(self, username: str) -> FetchResult:
        url = f"https://api.github.com/users/{username}"
        headers = dict(self.headers)
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with await self._client() as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 404:
            return FetchResult(status=404, fetched_url=url)
        if r.status_code != 200:
            log.warning("GitHub API returned %d for %s", r.status_code, username)
            return FetchResult(status=r.status_code, fetched_url=url)

        data: dict[str, Any] = r.json()
        bio_parts: list[str] = []
        for key in ("bio", "blog", "location", "email", "twitter_username", "company"):
            value = data.get(key)
            if not value:
                continue
            # Prefix certain fields so extractors have context
            if key == "twitter_username":
                bio_parts.append(f"@{value}")
            elif key == "blog" and not value.startswith("http"):
                bio_parts.append(f"https://{value}")
            else:
                bio_parts.append(str(value))

        return FetchResult(
            status=200,
            fetched_url=url,
            bio="\n".join(bio_parts),
            display_name=data.get("name"),
            avatar_url=data.get("avatar_url"),
            followers=data.get("followers"),
            extras={
                "public_repos": data.get("public_repos"),
                "created_at": data.get("created_at"),
                "html_url": data.get("html_url"),
            },
        )

    async def _fetch_gitlab(self, username: str) -> FetchResult:
        url = f"https://gitlab.com/api/v4/users?username={username}"
        async with await self._client() as client:
            r = await client.get(url)
        if r.status_code != 200:
            return FetchResult(status=r.status_code, fetched_url=url)
        users = r.json()
        if not users:
            return FetchResult(status=404, fetched_url=url)
        data = users[0]
        bio_parts: list[str] = []
        for key in ("bio", "location", "organization", "job_title", "website_url",
                    "linkedin", "twitter", "skype"):
            value = data.get(key)
            if value:
                bio_parts.append(str(value))
        return FetchResult(
            status=200,
            fetched_url=url,
            bio="\n".join(bio_parts),
            display_name=data.get("name"),
            avatar_url=data.get("avatar_url"),
            extras={
                "created_at": data.get("created_at"),
                "web_url": data.get("web_url"),
                "state": data.get("state"),
            },
        )

    async def _fetch_gravatar(self, username: str) -> FetchResult:
        """Fetch a public Gravatar profile by MD5 hash.

        `username` here is the 32-char lowercase MD5 of the user's email.
        Gravatar exposes profile data as JSON at `/<hash>.json` for any
        user who has filled in their profile (optional feature — a bare
        avatar without profile details returns 404 here).
        """
        url = f"https://www.gravatar.com/{username}.json"
        async with await self._client() as client:
            r = await client.get(url)
        if r.status_code != 200:
            return FetchResult(status=r.status_code, fetched_url=url)
        try:
            data = r.json()
        except Exception:
            return FetchResult(status=r.status_code, fetched_url=url)
        entries = data.get("entry") or []
        if not entries:
            return FetchResult(status=404, fetched_url=url)
        profile = entries[0]
        bio_parts: list[str] = []
        for key in (
            "displayName", "preferredUsername", "aboutMe",
            "currentLocation", "name",
        ):
            value = profile.get(key)
            if isinstance(value, dict):
                # "name" is a dict with formatted/givenName/familyName
                value = value.get("formatted") or " ".join(
                    v for v in (value.get("givenName"), value.get("familyName")) if v
                )
            if value:
                bio_parts.append(str(value))
        for entry in profile.get("urls") or []:
            if entry.get("value"):
                bio_parts.append(entry["value"])
        # "accounts" lists cross-linked profiles the user explicitly published
        for acc in profile.get("accounts") or []:
            if acc.get("url"):
                bio_parts.append(acc["url"])
            if acc.get("username"):
                bio_parts.append(f"@{acc['username']}")
        thumbnail = profile.get("thumbnailUrl")
        return FetchResult(
            status=200,
            fetched_url=url,
            bio="\n".join(bio_parts),
            display_name=(profile.get("displayName") or profile.get("preferredUsername")),
            avatar_url=thumbnail,
            extras={
                "profileUrl": profile.get("profileUrl"),
                "linked_accounts": [
                    a.get("shortname") for a in (profile.get("accounts") or [])
                ],
            },
        )

    # ------------------------------------------------------------------
    # Generic HTML fallback
    # ------------------------------------------------------------------

    _META_PATTERNS: tuple[re.Pattern, ...] = (
        re.compile(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
            re.IGNORECASE,
        ),
    )
    _TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

    async def _fetch_generic(self, profile_url: str) -> FetchResult:
        if not profile_url:
            return FetchResult(status=0, fetched_url="")
        try:
            async with await self._client() as client:
                r = await client.get(profile_url)
        except httpx.HTTPError as exc:
            log.debug("generic fetch failed: %s", exc)
            return FetchResult(status=0, fetched_url=profile_url)

        if r.status_code != 200:
            return FetchResult(status=r.status_code, fetched_url=profile_url)

        html = r.text
        parts: list[str] = []
        title_match = self._TITLE_RE.search(html)
        if title_match:
            parts.append(title_match.group(1).strip())
        for pattern in self._META_PATTERNS:
            for match in pattern.finditer(html):
                parts.append(match.group(1).strip())

        return FetchResult(
            status=200,
            fetched_url=profile_url,
            bio="\n".join(dict.fromkeys(parts)),  # dedup, preserve order
        )
