"""SoundCloud profile extractor.

SoundCloud serves a meaningful SSR HTML even though the site requires JS
to actually play tracks: the page includes a hydration payload with the
full user info (display name, city, avatar, follower count, …) inside a
`<script>window.__sc_hydration = ...</script>` block, plus fallback OG
tags and a JSON-LD ProfilePage block.

Extraction strategy:
  1. JSON-LD ProfilePage (most reliable)
  2. Hydration payload (richer fields — location, follower count)
  3. Meta tags (lowest fidelity)
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from src.connectors.platforms._base import (
    ExtractedProfile, extract_jsonld, get_og_or_twitter, jsonld_find_type,
    register_platform,
)


def matches(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("soundcloud.com")


_HYDRATION_RX = re.compile(
    r"window\.__sc_hydration\s*=\s*(\[.*?\]);",
    re.S,
)


def extract(html: str, url: str) -> ExtractedProfile:
    p = ExtractedProfile(platform="soundcloud")

    # Extract handle from URL path: /handle or /handle/track
    path = urlparse(url).path.strip("/").split("/")
    if path and path[0]:
        p.handle = path[0]

    # --- 1. JSON-LD ---
    blocks = extract_jsonld(html)
    person = jsonld_find_type(blocks, "MusicGroup", "Person", "ProfilePage")
    if person:
        # ProfilePage wraps mainEntity → Person/MusicGroup
        main = person.get("mainEntity") if isinstance(person.get("mainEntity"), dict) else person
        if isinstance(main, dict):
            p.display_name = p.display_name or main.get("name")
            p.bio = p.bio or main.get("description")
            img = main.get("image")
            if isinstance(img, str):
                p.avatar_url = p.avatar_url or img
            elif isinstance(img, dict):
                p.avatar_url = p.avatar_url or img.get("url") or img.get("contentUrl")

    # --- 2. Hydration payload ---
    m = _HYDRATION_RX.search(html)
    if m:
        try:
            hydration = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            hydration = []
        for item in hydration:
            if not isinstance(item, dict):
                continue
            if item.get("hydratable") != "user":
                continue
            data = item.get("data") or {}
            if not isinstance(data, dict):
                continue
            p.display_name = p.display_name or data.get("username") or data.get("full_name")
            p.handle = p.handle or data.get("permalink")
            city = data.get("city")
            country = data.get("country_code") or data.get("country")
            if city and country:
                p.location = f"{city}, {country}"
            elif city:
                p.location = city
            elif country:
                p.location = country
            p.bio = p.bio or data.get("description")
            p.followers = p.followers or data.get("followers_count")
            p.following = p.following or data.get("followings_count")
            p.posts_count = p.posts_count or data.get("track_count")
            avatar = data.get("avatar_url")
            if avatar:
                # SoundCloud avatars come in 100x100 by default; ask for a larger one
                p.avatar_url = p.avatar_url or avatar.replace("-large", "-t500x500")
            visuals = data.get("visuals") or {}
            if isinstance(visuals, dict):
                v_list = visuals.get("visuals") or []
                if v_list and isinstance(v_list, list):
                    first = v_list[0]
                    if isinstance(first, dict) and first.get("visual_url"):
                        p.cover_url = first["visual_url"]
            break

    # --- 3. Fallback meta tags ---
    if not p.display_name:
        p.display_name = get_og_or_twitter(html, "title")
    if not p.bio:
        p.bio = get_og_or_twitter(html, "description")
    if not p.avatar_url:
        p.avatar_url = get_og_or_twitter(html, "image")

    p.extras["platform"] = "soundcloud"
    return p


register_platform("soundcloud", matches, extract)
