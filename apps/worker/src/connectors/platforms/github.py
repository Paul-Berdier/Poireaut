"""GitHub user profile extractor.

GitHub serves clean SSR HTML for user profiles with stable semantic
attributes (`itemprop="*"`, `data-hovercard-type="user"`). We stay close
to the DOM: extract itemprops + the bio blurb + the follower summary
counter. No HTML parser dep — regex against the static markup.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, get_og_or_twitter, parse_count, register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.strip("/")
    # Only user/org pages, not arbitrary repos. A handle has one path segment
    # and no dots (avoids "github.com/foo/bar" being treated as a profile).
    if host != "github.com" and not host.endswith(".github.com"):
        return False
    segs = path.split("/")
    # Exclude /settings /sponsors /topics …
    return len(segs) == 1 and bool(segs[0]) and not segs[0].startswith("/")


_ITEMPROP_NAME_RX = re.compile(
    r'itemprop=["\']name["\'][^>]*>\s*([^<]+?)\s*<', re.I)
_ITEMPROP_DESC_RX = re.compile(
    r'<div[^>]+?class=["\'][^"\']*user-profile-bio[^"\']*["\'][^>]*>\s*<div[^>]*>\s*([^<]+?)\s*</div>',
    re.I | re.S)
# The "followers · following" line lives in <a href="?tab=followers"><span>123</span>
_FOLLOWERS_RX = re.compile(
    r'<a[^>]+?href=["\'][^"\']*tab=followers[^"\']*["\'][^>]*>.*?<span[^>]*>\s*([\d\.,KMkm]+)\s*</span>',
    re.I | re.S)
_FOLLOWING_RX = re.compile(
    r'<a[^>]+?href=["\'][^"\']*tab=following[^"\']*["\'][^>]*>.*?<span[^>]*>\s*([\d\.,KMkm]+)\s*</span>',
    re.I | re.S)
_LOCATION_RX = re.compile(
    r'<li[^>]+?itemprop=["\']homeLocation["\'][^>]*>.*?<span[^>]*>\s*([^<]+?)\s*</span>',
    re.I | re.S)
_WEBSITE_RX = re.compile(
    r'<li[^>]+?itemprop=["\']url["\'][^>]*>.*?<a[^>]+?href=["\']([^"\']+)["\']',
    re.I | re.S)
_AVATAR_RX = re.compile(
    r'<img[^>]+?class=["\'][^"\']*avatar-user[^"\']*["\'][^>]+?src=["\']([^"\']+)["\']',
    re.I)


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="github")

    p.handle = urlparse(url).path.strip("/")

    m = _ITEMPROP_NAME_RX.search(html)
    if m:
        p.display_name = m.group(1).strip()

    m = _ITEMPROP_DESC_RX.search(html)
    if m:
        p.bio = m.group(1).strip()

    m = _FOLLOWERS_RX.search(html)
    if m:
        p.followers = parse_count(m.group(1))
    m = _FOLLOWING_RX.search(html)
    if m:
        p.following = parse_count(m.group(1))

    m = _LOCATION_RX.search(html)
    if m:
        p.location = m.group(1).strip()

    m = _WEBSITE_RX.search(html)
    if m:
        # GitHub redirects external links; the href is the direct URL though
        p.website = m.group(1).strip()

    m = _AVATAR_RX.search(html)
    if m:
        p.avatar_url = m.group(1).strip()

    # Fallbacks
    if not p.display_name:
        p.display_name = get_og_or_twitter(html, "title")
    if not p.bio:
        p.bio = get_og_or_twitter(html, "description")
    if not p.avatar_url:
        p.avatar_url = get_og_or_twitter(html, "image")

    return p


register_platform("github", matches, extract)
