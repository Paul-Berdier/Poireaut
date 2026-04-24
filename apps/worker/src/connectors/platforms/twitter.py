"""Twitter / X profile extractor.

Twitter / X is heavily JS-rendered and increasingly locked down: the
server HTML for a profile page is mostly a shell that says "enable JS".
What's still reliable is the `og:*` and `twitter:*` meta tags they emit
for link-preview cards, plus the odd JSON-LD block.

This handler is intentionally modest: extract what the shell HTML offers
and stop. When Twitter returns 401/403/429 for server-side crawlers (which
it will increasingly), the upstream scraper reports that error cleanly.
"""
from __future__ import annotations

from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, clean_display_name, extract_jsonld,
    get_og_or_twitter, jsonld_find_type, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host not in {"twitter.com", "x.com", "mobile.twitter.com"}:
        return False
    segs = urlparse(url).path.strip("/").split("/")
    # Only profiles (/<handle>) — skip /<handle>/status/<id> tweets etc.
    return len(segs) == 1 and bool(segs[0])


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="twitter")
    p.handle = urlparse(url).path.strip("/").split("/")[0]

    # JSON-LD
    blocks = extract_jsonld(html)
    person = jsonld_find_type(blocks, "Person", "ProfilePage")
    if person:
        main = person.get("mainEntity") if isinstance(person.get("mainEntity"), dict) else person
        if isinstance(main, dict):
            p.display_name = p.display_name or main.get("name")
            p.bio = p.bio or main.get("description")

    # Meta fallback
    if not p.display_name:
        p.display_name = clean_display_name(get_og_or_twitter(html, "title") or "")
    if not p.bio:
        p.bio = get_og_or_twitter(html, "description")
    avatar = get_og_or_twitter(html, "image")
    if avatar:
        p.avatar_url = avatar

    return p


register_platform("twitter", matches, extract)
