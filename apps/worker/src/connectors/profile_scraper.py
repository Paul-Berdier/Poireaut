"""Generic profile scraper.

When we land on a public profile URL (coming from an `account` datapoint
produced by Holehe/Maigret), we want to lift structured signals out of it:
display name, avatar, bio. This doesn't try to be site-specific — it reads
the page's Open Graph and Twitter Card meta tags, which virtually every
public profile page exposes for link previews.

Input : DataType.URL (or DataType.ACCOUNT with a source_url)
Output:
  - DataType.NAME  (og:title / twitter:title  — usually "Display Name (@handle)")
  - DataType.PHOTO (og:image / twitter:image) when not a generic placeholder
  - DataType.OTHER ("bio:<text>") for og:description, when short and prose-like

No HTML parsing library — a few compiled regexes are enough and keep the
image tiny. We cap the body to 128 KB.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_BYTES = 128 * 1024


# Regex library — compiled once at import time.
# `property` and `name` can be in any order, quotes can be " or ', so
# we capture the `content` attribute permissively.
META_RX = {
    "og:title":       re.compile(r'<meta[^>]+?property=["\']og:title["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "og:description": re.compile(r'<meta[^>]+?property=["\']og:description["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "og:image":       re.compile(r'<meta[^>]+?property=["\']og:image["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "tw:title":       re.compile(r'<meta[^>]+?name=["\']twitter:title["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "tw:description": re.compile(r'<meta[^>]+?name=["\']twitter:description["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "tw:image":       re.compile(r'<meta[^>]+?name=["\']twitter:image["\'][^>]*?content=["\']([^"\']+)["\']', re.I),
    "title_tag":      re.compile(r"<title[^>]*>([^<]{3,300})</title>", re.I),
}

# Content that looks generic / useless — we drop findings that match these.
GENERIC_IMAGE_HINTS = (
    "default_profile",     # Twitter default avatar
    "default-avatar",
    "avatar-placeholder",
    "favicon",
    "logo",
    "/sprite/",
    ".svg",                # most SVGs are logos
)


@register
class ProfileScraperConnector(BaseConnector):
    name = "profile_scraper"
    display_name = "Profile Scraper — pull name/photo/bio from a profile URL"
    category = ConnectorCategory.SOCMINT
    description = (
        "Given a profile URL (from Holehe, Maigret, or entered manually), "
        "fetches the page and lifts the Open Graph / Twitter Card meta tags "
        "to extract a display name, avatar image and bio. No site-specific "
        "logic — works on every platform that supports link-preview cards."
    )
    homepage_url = None
    input_types = {DataType.URL, DataType.ACCOUNT}
    output_types = {DataType.NAME, DataType.PHOTO, DataType.OTHER}
    timeout_seconds = 25

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        url = input_value.strip()
        if input_type is DataType.ACCOUNT:
            # ACCOUNT values are bare domains ("twitter.com") — not scrape-able
            # alone. The orchestrator may pass the datapoint's source_url
            # separately in a future iteration; for now we require a URL input.
            if not url.startswith(("http://", "https://")):
                return ConnectorResult(
                    error="ACCOUNT input needs a full URL (use a URL datapoint)"
                )
        elif input_type is DataType.URL:
            if not url.startswith(("http://", "https://")):
                return ConnectorResult(error="URL must start with http:// or https://")
        else:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        try:
            async with httpx.AsyncClient(
                timeout=12.0,
                headers={"user-agent": USER_AGENT, "accept-language": "en-US,en;q=0.5"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"HTTP error: {type(exc).__name__}: {exc}")

        if resp.status_code >= 400:
            return ConnectorResult(
                error=f"HTTP {resp.status_code} — page unreachable or blocked"
            )

        body = resp.text[:MAX_BYTES] if resp.content else ""
        if not body:
            return ConnectorResult(findings=[], raw_output={"empty": True})

        meta = _extract_meta(body)

        findings: list[Finding] = []

        # --- NAME ---
        title = meta.get("og:title") or meta.get("tw:title") or meta.get("title_tag")
        if title:
            cleaned = _clean_title(title)
            if cleaned:
                findings.append(
                    Finding(
                        data_type=DataType.NAME,
                        value=cleaned,
                        confidence=0.7,
                        source_url=str(resp.url),
                        extracted_at=now_utc(),
                        notes=f"Nom affiché sur {_host(str(resp.url))}",
                        raw={"source_field": _which_field(meta, ("og:title", "tw:title", "title_tag"))},
                    )
                )

        # --- PHOTO ---
        image = meta.get("og:image") or meta.get("tw:image")
        if image and not _looks_generic(image):
            findings.append(
                Finding(
                    data_type=DataType.PHOTO,
                    value=image,
                    confidence=0.75,
                    source_url=str(resp.url),
                    extracted_at=now_utc(),
                    notes=f"Photo de profil (og:image) sur {_host(str(resp.url))}",
                )
            )

        # --- BIO ---
        desc = meta.get("og:description") or meta.get("tw:description")
        if desc and 10 <= len(desc) <= 500:
            findings.append(
                Finding(
                    data_type=DataType.OTHER,
                    value=f"bio: {desc.strip()}",
                    confidence=0.7,
                    source_url=str(resp.url),
                    extracted_at=now_utc(),
                    notes=f"Bio affichée sur {_host(str(resp.url))}",
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={
                "fields_found": sorted(k for k, v in meta.items() if v),
                "final_url": str(resp.url),
            },
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=5, headers={"user-agent": USER_AGENT}) as c:
                r = await c.get("https://example.com")
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD


# ─── Helpers ──────────────────────────────────────────────────

def _extract_meta(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, rx in META_RX.items():
        m = rx.search(body)
        if m:
            out[key] = _html_unescape(m.group(1).strip())
    return out


def _clean_title(raw: str) -> str | None:
    # Many sites append " | Site Name" or " - Site Name" — trim it if short
    cleaned = raw.strip()
    # Drop site-name suffix if separator is ' | ' or ' - ' near the end
    for sep in (" | ", " - ", " — "):
        if sep in cleaned:
            head, _, tail = cleaned.rpartition(sep)
            if len(tail) <= 30 and len(head) >= 2:
                cleaned = head
    cleaned = cleaned.strip()
    if len(cleaned) < 2 or len(cleaned) > 150:
        return None
    return cleaned


def _looks_generic(image_url: str) -> bool:
    lowered = image_url.lower()
    return any(hint in lowered for hint in GENERIC_IMAGE_HINTS)


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _which_field(meta: dict, preferred: tuple[str, ...]) -> str | None:
    for p in preferred:
        if meta.get(p):
            return p
    return None


def _html_unescape(s: str) -> str:
    try:
        from html import unescape
        return unescape(s)
    except Exception:  # noqa: BLE001
        return s
