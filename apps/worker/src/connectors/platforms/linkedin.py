"""LinkedIn profile extractor.

LinkedIn returns a 999 status code or an authwall HTML to unauthenticated
crawlers. Extraction is therefore best-effort: we lift og:* meta tags
when present (which is rare from server-side crawlers) and return what
we get. When blocked, the upstream scraper reports the HTTP error cleanly
and no finding is produced.
"""
from __future__ import annotations

from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, clean_display_name, get_og_or_twitter, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host not in {"linkedin.com", "fr.linkedin.com", "uk.linkedin.com"}:
        return False
    path = urlparse(url).path.strip("/")
    return path.startswith(("in/", "company/", "school/"))


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="linkedin")
    segs = urlparse(url).path.strip("/").split("/")
    if len(segs) >= 2 and segs[0] in {"in", "company", "school"}:
        p.handle = segs[1]

    og_title = get_og_or_twitter(html, "title")
    if og_title:
        p.display_name = clean_display_name(og_title)
    desc = get_og_or_twitter(html, "description")
    if desc:
        p.bio = desc
    avatar = get_og_or_twitter(html, "image")
    if avatar:
        p.avatar_url = avatar

    return p


register_platform("linkedin", matches, extract)
