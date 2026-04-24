"""Shared types and registry for platform-specific profile extractors.

A platform handler looks at a profile URL + its HTML and produces a
structured `ExtractedProfile` bag. The scraper converts this bag to
Finding objects.

Handlers are intentionally small and obvious — they use regexes against
the raw HTML rather than parsing the DOM, both to keep the image lean
and because the HTML we get from servers is static (no JS-rendered bits).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractedProfile:
    """Structured profile info lifted from a page.

    Every field is optional — a handler should set only what it's sure
    about. `platform` identifies which extractor produced the data.
    """
    platform: str | None = None          # "soundcloud", "github", "generic", …
    handle: str | None = None             # "6ssay", "torvalds", …
    display_name: str | None = None       # "Xssay", "Linus Torvalds"
    bio: str | None = None                # free-form description
    location: str | None = None           # "Toulouse, France"
    avatar_url: str | None = None
    cover_url: str | None = None          # banner/cover image if different from avatar
    followers: int | None = None
    following: int | None = None
    posts_count: int | None = None
    website: str | None = None            # external link the user put on their profile
    extras: dict = field(default_factory=dict)  # platform-specific bits

    def is_empty(self) -> bool:
        return not any([
            self.handle, self.display_name, self.bio, self.location,
            self.avatar_url, self.cover_url, self.followers, self.posts_count,
            self.website,
        ])

    def fields_filled(self) -> list[str]:
        names = ["handle", "display_name", "bio", "location", "avatar_url",
                 "cover_url", "followers", "following", "posts_count", "website"]
        return [n for n in names if getattr(self, n)]


# ── Registry ─────────────────────────────────────────

PlatformMatcher = Callable[[str], bool]
PlatformExtractor = Callable[[str, str], ExtractedProfile]  # (html, url) → profile

_PLATFORM_HANDLERS: list[tuple[str, PlatformMatcher, PlatformExtractor]] = []


def register_platform(
    name: str,
    matcher: PlatformMatcher,
    extractor: PlatformExtractor,
) -> None:
    """Register a platform handler. First-registered wins on match."""
    _PLATFORM_HANDLERS.append((name, matcher, extractor))
    logger.debug("Registered platform handler: %s", name)


def find_handler(url: str) -> Optional[tuple[str, PlatformExtractor]]:
    """Return (name, extractor) of the first registered handler matching url."""
    for name, matcher, extractor in _PLATFORM_HANDLERS:
        try:
            if matcher(url):
                return name, extractor
        except Exception:  # noqa: BLE001
            continue
    return None


def all_registered() -> list[str]:
    return [name for (name, _, _) in _PLATFORM_HANDLERS]


# ── Shared HTML helpers used by most handlers ────────

def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I | re.S)


_META_RX_CACHE: dict[str, re.Pattern[str]] = {}


def get_meta(html: str, key: str, kind: str = "property") -> str | None:
    """Extract a <meta property="og:…"> or <meta name="…"> content value."""
    cache_key = f"{kind}:{key}"
    rx = _META_RX_CACHE.get(cache_key)
    if rx is None:
        rx = _rx(
            rf'<meta[^>]+?{kind}=["\']{re.escape(key)}["\'][^>]*?content=["\']([^"\']+)["\']'
        )
        _META_RX_CACHE[cache_key] = rx
    m = rx.search(html)
    return _html_unescape(m.group(1).strip()) if m else None


def get_meta_any(html: str, keys: list[str], kind: str = "property") -> str | None:
    """First non-empty meta match across a list of keys."""
    for k in keys:
        v = get_meta(html, k, kind)
        if v:
            return v
    return None


# Prefer twitter:* for titles when og:* is generic
def get_og_or_twitter(html: str, name: str) -> str | None:
    """og:<name> falling back to twitter:<name>."""
    og = get_meta(html, f"og:{name}", "property")
    if og:
        return og
    return get_meta(html, f"twitter:{name}", "name")


def extract_title_tag(html: str) -> str | None:
    """Fallback to the <title> tag when OG/Twitter are missing."""
    m = _rx(r"<title[^>]*>([^<]{2,300})</title>").search(html)
    if not m:
        return None
    return _html_unescape(m.group(1)).strip()


def extract_jsonld(html: str) -> list[dict]:
    """Extract all <script type="application/ld+json"> payloads.

    JSON-LD is schema.org structured data. Most big platforms ship a
    ProfilePage or Person block with name, description, image, url, etc.
    """
    import json

    blocks: list[dict] = []
    rx = _rx(r'<script[^>]+?type=["\']application/ld\+json["\'][^>]*>(.*?)</script>')
    for m in rx.finditer(html):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            # Some sites ship multiple JSON objects concatenated — try arrays.
            try:
                data = json.loads(f"[{raw}]")
            except Exception:  # noqa: BLE001
                continue
        if isinstance(data, list):
            blocks.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            # Some blocks wrap in @graph
            if "@graph" in data and isinstance(data["@graph"], list):
                blocks.extend(x for x in data["@graph"] if isinstance(x, dict))
            else:
                blocks.append(data)
    return blocks


def jsonld_find_type(blocks: list[dict], *types: str) -> dict | None:
    """Return the first block whose @type matches one of the given types."""
    wanted = {t.lower() for t in types}
    for b in blocks:
        t = b.get("@type")
        if isinstance(t, str) and t.lower() in wanted:
            return b
        if isinstance(t, list) and any(
            isinstance(x, str) and x.lower() in wanted for x in t
        ):
            return b
    return None


def _html_unescape(s: str) -> str:
    try:
        from html import unescape
        return unescape(s)
    except Exception:  # noqa: BLE001
        return s


# Placeholder-filter for avatars — drops generic ones.
GENERIC_IMAGE_HINTS = (
    "default_profile", "default-avatar", "avatar-placeholder",
    "favicon", "logo-",
    "/sprite/", "/static/",
)


def looks_generic_image(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in GENERIC_IMAGE_HINTS)


def clean_display_name(raw: str) -> str | None:
    """Strip " | Site Name" / " — Site Name" trailers when obvious."""
    if not raw:
        return None
    cleaned = raw.strip()
    for sep in (" | ", " - ", " — ", " · ", " @ "):
        if sep in cleaned:
            head, _, tail = cleaned.rpartition(sep)
            if 2 <= len(tail) <= 30 and len(head) >= 2:
                cleaned = head
    cleaned = cleaned.strip()
    if len(cleaned) < 2 or len(cleaned) > 150:
        return None
    return cleaned


def parse_count(raw: str | int | None) -> int | None:
    """Parse '12.3K', '1,234', '1 234', '2M' into an int."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = str(raw).strip().lower().replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        if s.endswith("k"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("b"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(float(s))
    except ValueError:
        return None
