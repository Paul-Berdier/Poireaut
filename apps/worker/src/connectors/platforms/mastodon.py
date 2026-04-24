"""Mastodon profile extractor.

Mastodon profile pages (federated across thousands of instances) share
the same template: title is "Display Name (@handle@instance)",
description is the user bio, image is the avatar. We match on the URL
shape `/@handle` at any host — which is generous but correct since that
path pattern is near-exclusive to Mastodon in the wild.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, clean_display_name, get_og_or_twitter, register_platform,
)


def matches(url: str) -> bool:
    # Any host, path must start with "/@something" and not be a YouTube handle
    host = urlparse(url).netloc.lower().lstrip("www.")
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        return False
    path = urlparse(url).path
    return bool(re.match(r"^/@[^/]+/?$", path))


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="mastodon")
    m = re.match(r"^/@([^/]+)", urlparse(url).path)
    if m:
        p.handle = m.group(1)

    og_title = get_og_or_twitter(html, "title") or ""
    p.display_name = clean_display_name(og_title.split("(@", 1)[0].strip()) or og_title or None
    p.bio = get_og_or_twitter(html, "description")
    avatar = get_og_or_twitter(html, "image")
    if avatar:
        p.avatar_url = avatar

    return p


register_platform("mastodon", matches, extract)
