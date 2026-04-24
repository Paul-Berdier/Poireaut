"""Profile scraper — generic + platform-specific.

Flow:
  1. HTTP GET the URL with a real browser user-agent, follow redirects.
  2. If the URL matches a registered platform handler, run that.
  3. Otherwise run a generic extractor: JSON-LD (schema.org Person /
     ProfilePage / Organization) → OG/Twitter meta → <title> / <h1>.
  4. Convert the ExtractedProfile into Finding objects.

The scraper always records what it actually retrieved in raw_output,
so the admin runs panel shows whether a 0-finding outcome was because
of blocked access, empty extraction, or both.

Input : DataType.URL (or DataType.ACCOUNT with a URL value)
Output: DataType.NAME, DataType.PHOTO, DataType.ADDRESS (for location),
        DataType.URL (external website if the profile links one),
        DataType.OTHER for bio and follower/post counts.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.connectors.platforms._base import (
    ExtractedProfile, extract_jsonld, get_og_or_twitter, extract_title_tag,
    jsonld_find_type, find_handler, clean_display_name,
    looks_generic_image, all_registered,
)
# Force registration of every platform handler
from src.connectors import platforms  # noqa: F401
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
MAX_BYTES = 256 * 1024  # 256KB ceiling — big enough for hydration payloads


@register
class ProfileScraperConnector(BaseConnector):
    name = "profile_scraper"
    display_name = "Profile Scraper — generic + per-platform extraction"
    category = ConnectorCategory.SOCMINT
    description = (
        "Fetches a profile URL and lifts structured info from it: display "
        "name, avatar, bio, location, follower count, external website. "
        "Dedicated handlers for SoundCloud, GitHub, Twitter/X, Instagram, "
        "YouTube, LinkedIn, Reddit, Mastodon. Falls back to a generic "
        "JSON-LD / OpenGraph extractor everywhere else."
    )
    homepage_url = None
    input_types = {DataType.URL, DataType.ACCOUNT}
    output_types = {
        DataType.NAME, DataType.PHOTO, DataType.ADDRESS,
        DataType.URL, DataType.OTHER,
    }
    timeout_seconds = 30

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        url = input_value.strip()
        if not url.startswith(("http://", "https://")):
            return ConnectorResult(
                error=f"Not a full URL: {url!r}. Expected http(s)://…"
            )
        if input_type not in (DataType.URL, DataType.ACCOUNT):
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "user-agent": USER_AGENT,
                    "accept-language": "en-US,en;q=0.7,fr;q=0.5",
                    "accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,*/*;q=0.8"
                    ),
                },
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return ConnectorResult(
                error=f"HTTP error: {type(exc).__name__}: {exc}"
            )

        if resp.status_code >= 400:
            # Classify the error so the UI can show something useful.
            hint = _http_error_hint(resp.status_code)
            return ConnectorResult(
                error=f"HTTP {resp.status_code} {hint}",
                raw_output={
                    "final_url": str(resp.url),
                    "status_code": resp.status_code,
                },
            )

        body = resp.text[:MAX_BYTES] if resp.content else ""
        final_url = str(resp.url)

        if not body:
            return ConnectorResult(
                findings=[],
                raw_output={"final_url": final_url, "empty_body": True},
            )

        # ── Pick a handler ──
        handler_info = find_handler(final_url) or find_handler(url)
        if handler_info:
            handler_name, extractor = handler_info
            try:
                profile = extractor(body, final_url)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Platform handler %s crashed", handler_name)
                profile = _generic_extract(body, final_url)
                profile.extras["handler_error"] = f"{type(exc).__name__}: {exc}"
            else:
                profile.platform = profile.platform or handler_name
        else:
            profile = _generic_extract(body, final_url)

        findings = _profile_to_findings(profile, final_url)

        return ConnectorResult(
            findings=findings,
            raw_output={
                "final_url": final_url,
                "handler": profile.platform or "generic",
                "fields_filled": profile.fields_filled(),
                "bytes_read": len(body),
            },
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(
                timeout=6, headers={"user-agent": USER_AGENT}
            ) as c:
                r = await c.get("https://example.com")
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD


# ─── Generic extraction ───────────────────────────────────────

def _generic_extract(html: str, url: str) -> ExtractedProfile:
    """Fallback when no platform handler matches.

    Priority: JSON-LD Person/ProfilePage > OG/Twitter meta > <title>/<h1>.
    """
    p = ExtractedProfile(platform="generic")

    blocks = extract_jsonld(html)
    person = jsonld_find_type(blocks, "Person", "ProfilePage", "Organization")
    if person:
        main = person.get("mainEntity") if isinstance(person.get("mainEntity"), dict) else person
        if isinstance(main, dict):
            p.display_name = _maybe_str(main.get("name"))
            p.bio = _maybe_str(main.get("description"))
            img = main.get("image")
            if isinstance(img, str):
                p.avatar_url = img
            elif isinstance(img, dict):
                p.avatar_url = img.get("url") or img.get("contentUrl")
            addr = main.get("address")
            if isinstance(addr, dict):
                parts = [
                    addr.get("streetAddress"), addr.get("addressLocality"),
                    addr.get("addressRegion"), addr.get("addressCountry"),
                ]
                parts = [p for p in parts if p]
                if parts:
                    p.location = ", ".join(parts)
            elif isinstance(addr, str):
                p.location = addr
            same_as = main.get("sameAs")
            if isinstance(same_as, str):
                p.website = same_as
            elif isinstance(same_as, list) and same_as:
                p.website = next((x for x in same_as if isinstance(x, str)), None)

    # OG / Twitter
    if not p.display_name:
        p.display_name = clean_display_name(get_og_or_twitter(html, "title") or "")
    if not p.bio:
        p.bio = get_og_or_twitter(html, "description")
    if not p.avatar_url:
        p.avatar_url = get_og_or_twitter(html, "image")

    # Final fallback: <title>, then first <h1>
    if not p.display_name:
        p.display_name = clean_display_name(extract_title_tag(html) or "")
    if not p.display_name:
        m = re.search(r"<h1[^>]*>\s*([^<]{2,120})\s*</h1>", html, re.I)
        if m:
            p.display_name = clean_display_name(m.group(1))

    return p


def _maybe_str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _profile_to_findings(profile: ExtractedProfile, url: str) -> list[Finding]:
    out: list[Finding] = []
    plat = profile.platform or "generic"
    host = _host(url)
    src = profile.platform or host

    if profile.display_name:
        out.append(Finding(
            data_type=DataType.NAME,
            value=profile.display_name,
            confidence=0.8 if plat != "generic" else 0.65,
            source_url=url,
            extracted_at=now_utc(),
            notes=f"Nom affiché sur {src}",
            raw={"extractor": plat, "handle": profile.handle},
        ))

    if profile.avatar_url and not looks_generic_image(profile.avatar_url):
        out.append(Finding(
            data_type=DataType.PHOTO,
            value=profile.avatar_url,
            confidence=0.75,
            source_url=url,
            extracted_at=now_utc(),
            notes=f"Photo de profil sur {src}",
        ))

    if profile.location:
        out.append(Finding(
            data_type=DataType.ADDRESS,
            value=profile.location,
            confidence=0.7,
            source_url=url,
            extracted_at=now_utc(),
            notes=f"Localisation déclarée sur {src}",
        ))

    if profile.bio and 5 <= len(profile.bio) <= 500:
        out.append(Finding(
            data_type=DataType.OTHER,
            value=f"bio: {profile.bio.strip()}",
            confidence=0.7,
            source_url=url,
            extracted_at=now_utc(),
            notes=f"Bio sur {src}",
        ))

    if profile.website and profile.website.startswith(("http://", "https://")):
        out.append(Finding(
            data_type=DataType.URL,
            value=profile.website,
            confidence=0.8,
            source_url=url,
            extracted_at=now_utc(),
            notes=f"Site web déclaré sur {src}",
        ))

    # Expose follower / posts as OTHER data so it's at least visible.
    stats_parts = []
    if profile.followers is not None:
        stats_parts.append(f"{profile.followers:,} abonnés")
    if profile.following is not None:
        stats_parts.append(f"{profile.following:,} abonnements")
    if profile.posts_count is not None:
        stats_parts.append(f"{profile.posts_count:,} posts")
    if stats_parts:
        out.append(Finding(
            data_type=DataType.OTHER,
            value=f"stats ({src}): " + " · ".join(stats_parts),
            confidence=0.9,
            source_url=url,
            extracted_at=now_utc(),
            notes="Compteurs publics extraits du profil",
        ))

    return out


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _http_error_hint(code: int) -> str:
    """Friendly hint explaining common HTTP errors to the user."""
    if code == 401:
        return "(authentification requise)"
    if code == 403:
        return "(accès refusé au crawler)"
    if code == 404:
        return "(profil introuvable)"
    if code == 410:
        return "(profil supprimé)"
    if code == 429:
        return "(rate-limited)"
    if 500 <= code < 600:
        return "(erreur serveur)"
    return ""
