"""Instagram profile extractor.

Instagram SSR serves og:title / og:description / og:image populated with
"Real Name (@handle) • Instagram photos and videos" — we parse both the
handle and real name out of that string, plus the description (which is
the first 150 chars of the bio + a follower count formatted summary).

The follower count lives in the `<meta name="description">` as
"XXX Followers, YY Following, ZZ Posts - See Instagram …".
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, get_meta, get_og_or_twitter, parse_count, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host != "instagram.com":
        return False
    segs = urlparse(url).path.strip("/").split("/")
    return len(segs) == 1 and bool(segs[0]) and segs[0] not in {
        "explore", "reels", "stories", "direct", "accounts",
    }


# Matches "12.3K Followers, 456 Following, 78 Posts - ..."
_COUNTS_RX = re.compile(
    r"([\d\.,KMBkmb]+)\s*Followers?[^\d]+([\d\.,KMBkmb]+)\s*Following[^\d]+([\d\.,KMBkmb]+)\s*Posts?",
    re.I,
)


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="instagram")
    p.handle = urlparse(url).path.strip("/").split("/")[0]

    og_title = get_og_or_twitter(html, "title") or ""
    # Format: "Real Name (@handle) • Instagram photos and videos"
    m = re.match(r"\s*(.+?)\s*\(@([^)]+)\)", og_title)
    if m:
        p.display_name = m.group(1).strip()
        p.handle = m.group(2).strip() or p.handle

    # description meta has bio + counts
    desc = get_meta(html, "description", kind="name") or get_og_or_twitter(html, "description") or ""
    counts = _COUNTS_RX.search(desc)
    if counts:
        p.followers = parse_count(counts.group(1))
        p.following = parse_count(counts.group(2))
        p.posts_count = parse_count(counts.group(3))
        # The part after " - " usually has the actual bio text
        after = desc.split(" - ", 1)
        if len(after) == 2:
            # "See Instagram photos and videos from Name (@handle) "bio text""
            tail = after[1]
            q = re.search(r'"(.+?)"', tail)
            if q:
                p.bio = q.group(1)
    else:
        p.bio = desc

    avatar = get_og_or_twitter(html, "image")
    if avatar:
        p.avatar_url = avatar

    return p


register_platform("instagram", matches, extract)
