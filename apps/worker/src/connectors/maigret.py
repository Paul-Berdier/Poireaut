"""Maigret connector — username profile discovery across ~2500 sites.

We only emit ACCOUNT findings now (previously we also emitted a redundant
URL finding for every hit). The `value` of an ACCOUNT is the full profile
URL so it's immediately useful: the UI renders it as a clickable link,
the profile_scraper can accept it as input, and the user sees a single
node per platform instead of two.

Site filtering:
  Maigret bundles ~2500 sites, including a long tail of regional forums
  (mainly .ru / .pl / .ua / .by) that produce massive noise for
  French-speaking investigators. We filter the results by TLD: only
  globally-recognized platforms + Western European/American TLDs are
  kept. The full Maigret search still runs (faster than re-implementing
  site filtering inside Maigret), but we drop the irrelevant hits
  before returning findings.

Input : DataType.USERNAME
Output: DataType.ACCOUNT (one per matched site)
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

from src.connectors._signals import build
from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)


# ── TLDs we *keep* — globally relevant for French/Western investigations.
# Adding more is one-line. Removing is one-line.
ALLOWED_TLDS: frozenset[str] = frozenset({
    "com", "net", "org", "io", "co", "app", "ai", "dev", "me", "tv",
    # European
    "fr", "be", "ch", "lu", "ca",
    "de", "at", "nl",
    "uk", "ie",
    "es", "pt", "it",
    # Other major Western
    "us", "edu", "gov", "mil",
    "au", "nz",
    # Latin Am
    "br", "mx", "ar",
    # Major creator platforms / niche but high-signal
    "gg", "fm", "tv",
})

# ── TLDs we *block* — high-noise regional, mostly Slavic/Asian forums.
# A site appearing in BLOCKED_TLDS overrides ALLOWED_TLDS so a .ru.com
# trick can't sneak through.
BLOCKED_TLDS: frozenset[str] = frozenset({
    "ru", "su", "by", "ua", "kz", "uz",
    "pl", "cz", "sk", "hu", "ro", "bg",
    "rs", "hr", "ba", "mk", "si",
    "tr", "ge", "az",
    "cn", "jp", "kr", "vn", "th", "tw", "hk",
    "ir", "iq", "sa", "ae",
})

# ── Sites we always keep regardless of TLD (high-value globally).
# Maigret's `site_name` (matched case-insensitively).
ALWAYS_KEEP_SITES: frozenset[str] = frozenset(s.lower() for s in {
    "GitHub", "GitLab", "Bitbucket",
    "Twitter", "X", "Mastodon",
    "Instagram", "Facebook", "LinkedIn",
    "Reddit", "Snapchat", "Threads",
    "TikTok", "YouTube", "Vimeo",
    "Discord", "Telegram", "Signal", "WhatsApp",
    "Steam", "Twitch", "PlayStation Network", "Xbox",
    "SoundCloud", "Spotify", "Bandcamp", "Last.fm", "Mixcloud",
    "Patreon", "Substack", "Medium", "Ghost",
    "DeviantArt", "ArtStation", "Behance", "Dribbble",
    "Stack Overflow", "Codepen", "Replit",
    "Pinterest", "Flickr", "Imgur", "500px",
    "PayPal", "Venmo", "Cash App",
    "Strava", "Goodreads", "MyAnimeList", "Letterboxd",
    "Roblox", "Minecraft", "Wikipedia",
})


def _is_site_allowed(site_name: str, url: str) -> tuple[bool, str]:
    """Decide whether to keep a Maigret hit.

    Returns (keep, reason) where reason is a short explanation used in
    debug logging and the raw_output for transparency.
    """
    if site_name.lower() in ALWAYS_KEEP_SITES:
        return True, "site whitelist"

    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return False, "malformed url"
    # Extract last TLD segment (handles co.uk → uk)
    parts = host.split(".")
    if len(parts) < 2:
        return False, f"no TLD in {host}"
    tld = parts[-1]

    if tld in BLOCKED_TLDS:
        return False, f".{tld} blocked"
    if tld in ALLOWED_TLDS:
        return True, f".{tld} allowed"
    return False, f".{tld} not in allowlist"


@register
class MaigretConnector(BaseConnector):
    name = "maigret"
    display_name = "Maigret — username profile discovery"
    category = ConnectorCategory.USERNAME
    description = (
        "Scans ~2500 public sites to find where a username has registered a "
        "profile. No authentication, no notifications. Results are filtered "
        "to globally-relevant platforms (we skip regional .ru/.pl/etc. "
        "forums that mostly produce noise for French investigations)."
    )
    homepage_url = "https://github.com/soxoj/maigret"
    input_types = {DataType.USERNAME}
    output_types = {DataType.ACCOUNT}
    timeout_seconds = 180

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.USERNAME:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        username = input_value.strip()
        if not username or " " in username:
            return ConnectorResult(error="Username must be non-empty and whitespace-free")

        try:
            import maigret as maigret_pkg
            from maigret.sites import MaigretDatabase
            from maigret.maigret import maigret as maigret_run
        except ImportError as exc:
            return ConnectorResult(error=f"Maigret library not available: {exc}")

        try:
            db_path = os.path.join(maigret_pkg.__path__[0], "resources", "data.json")
            db = MaigretDatabase().load_from_file(db_path)
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Failed to load Maigret site DB: {exc}")

        # Load the runtime blacklist from DB. If the table isn't ready
        # yet (fresh deploy, periodic task hasn't run) we get an empty
        # set and Maigret falls back to its full site list.
        disabled_sites = await _load_disabled_sites_safe()
        if disabled_sites:
            logger.info(
                "Maigret: %d sites in DB blacklist will be skipped",
                len(disabled_sites),
            )

        # Filter the site dict BEFORE passing it to Maigret. Maigret's
        # own `disabled_sites_set` doesn't exist in all versions; doing
        # the filter ourselves works on every Maigret release.
        active_sites = {
            name: site for name, site in db.sites_dict.items()
            if name not in disabled_sites
        }

        try:
            results: dict[str, Any] = await maigret_run(
                username=username,
                site_dict=active_sites,
                logger=logger,
                timeout=15,
                id_type="username",
                max_connections=50,
                forced=False,
                no_progressbar=True,
                cookies=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Maigret search failed")
            return ConnectorResult(error=f"Maigret search failed: {type(exc).__name__}: {exc}")

        findings: list[Finding] = []
        seen_urls: set[str] = set()
        filtered_out: dict[str, int] = {}    # reason → count, for debug raw

        for site_name, info in (results or {}).items():
            if not isinstance(info, dict):
                continue
            status = info.get("status")
            try:
                if not (status and status.is_found()):
                    continue
            except Exception:  # noqa: BLE001
                continue

            url = info.get("url_user") or info.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            keep, reason = _is_site_allowed(site_name, url)
            if not keep:
                filtered_out[reason] = filtered_out.get(reason, 0) + 1
                continue

            # Confidence: high prior because Maigret has already content-matched.
            # Boosted for the well-known platforms (whitelist), lighter for
            # sites we don't recognize but kept by TLD.
            is_major = site_name.lower() in ALWAYS_KEEP_SITES
            cb = build(
                "maigret.content_match",
                0.90 if is_major else 0.78,
                f"Maigret a confirmé un profil sur {site_name}",
            )
            if is_major:
                cb.add(
                    "maigret.major_platform", 0.05,
                    "Plateforme grand public (whitelist)",
                )

            findings.append(
                Finding(
                    data_type=DataType.ACCOUNT,
                    value=url,
                    confidence=round(cb.compose(), 2),
                    source_url=url,
                    extracted_at=now_utc(),
                    raw={
                        "site": site_name, "url": url, "_signals": cb.to_raw(),
                    },
                    notes=f"Profil trouvé sur {site_name}",
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={
                "sites_scanned": len(results or {}),
                "matches_raw": len(seen_urls),
                "matches_kept": len(findings),
                "filtered_out": filtered_out,
            },
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            import maigret  # noqa: F401
            return HealthStatus.OK
        except ImportError:
            return HealthStatus.DEAD


async def _load_disabled_sites_safe() -> set[str]:
    """Read the maigret_site_health blacklist from DB. Returns an empty
    set if the table doesn't exist yet (fresh deploy) or any other error
    so we never block Maigret's normal operation.
    """
    try:
        from src.tasks import _get_session
        from src._maigret_health import load_disabled_sites
    except ImportError:
        return set()
    try:
        Session = _get_session()
        async with Session() as db:
            return await load_disabled_sites(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load Maigret blacklist (will use full list): %s", exc)
        return set()
