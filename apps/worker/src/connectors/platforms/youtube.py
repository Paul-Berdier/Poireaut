"""YouTube channel extractor.

YouTube channel pages embed a generous JSON payload in an
`ytInitialData` script tag with handle, name, subscriber count and avatar.
OG/Twitter meta tags also carry the essentials as fallback.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, extract_jsonld, get_meta, get_og_or_twitter,
    jsonld_find_type, parse_count, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host not in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return False
    path = urlparse(url).path
    return (
        path.startswith("/@")        # modern handle
        or path.startswith("/c/")    # legacy custom
        or path.startswith("/channel/")
        or path.startswith("/user/")
    )


_YT_INITIAL_RX = re.compile(
    r"var\s+ytInitialData\s*=\s*(\{.+?\});",
    re.S,
)
_SUBSCRIBER_RX = re.compile(
    r'"([\d\.,KMBkmb]+)\s*subscribers?"',
    re.I,
)


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="youtube")

    # Handle from the path
    path = urlparse(url).path.strip("/")
    if path.startswith("@"):
        p.handle = path[1:].split("/")[0]
    else:
        segs = path.split("/")
        if len(segs) >= 2 and segs[0] in {"c", "channel", "user"}:
            p.handle = segs[1]

    # JSON-LD Person/Organization
    blocks = extract_jsonld(html)
    person = jsonld_find_type(blocks, "Person", "Organization")
    if person:
        p.display_name = p.display_name or person.get("name")
        p.bio = p.bio or person.get("description")
        img = person.get("image")
        if isinstance(img, str):
            p.avatar_url = p.avatar_url or img
        elif isinstance(img, dict):
            p.avatar_url = p.avatar_url or img.get("url")

    # ytInitialData — deeply nested. We just search for subscriberCountText.
    yt = _YT_INITIAL_RX.search(html)
    if yt:
        sub_match = _SUBSCRIBER_RX.search(yt.group(1))
        if sub_match:
            p.followers = parse_count(sub_match.group(1))
        # Try to fish the channel name from the payload
        name_m = re.search(r'"title":"([^"]+)","navigationEndpoint"', yt.group(1))
        if name_m and not p.display_name:
            p.display_name = name_m.group(1)

    # Meta fallbacks
    if not p.display_name:
        p.display_name = get_og_or_twitter(html, "title")
    if not p.bio:
        p.bio = get_og_or_twitter(html, "description") or get_meta(html, "description", "name")
    if not p.avatar_url:
        p.avatar_url = get_og_or_twitter(html, "image")

    return p


register_platform("youtube", matches, extract)
