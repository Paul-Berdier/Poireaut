"""Reddit user profile extractor.

Reddit is the easiest of the lot: every user page has a JSON sibling at
`<url>/about.json` returning a `data` dict with exactly what we want.
This handler's `extract` still gets the HTML (the scraper fetches the
page URL by default), so we ignore the HTML and fall back to OG meta —
but we mark the result so an upstream consumer could fetch .json instead
in a future iteration.
"""
from __future__ import annotations

from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, get_og_or_twitter, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    if not host.endswith("reddit.com"):
        return False
    path = urlparse(url).path.strip("/")
    return path.startswith(("u/", "user/"))


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="reddit")
    segs = urlparse(url).path.strip("/").split("/")
    if len(segs) >= 2 and segs[0] in {"u", "user"}:
        p.handle = segs[1]

    og_title = get_og_or_twitter(html, "title")
    if og_title:
        p.display_name = og_title
    desc = get_og_or_twitter(html, "description")
    if desc:
        p.bio = desc
    avatar = get_og_or_twitter(html, "image")
    if avatar:
        p.avatar_url = avatar

    return p


register_platform("reddit", matches, extract)
