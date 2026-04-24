"""Platform-specific extraction handlers.

Each handler module registers itself via `@register_platform` and provides:
  - a `matches(url) -> bool` classifier
  - an `extract(html, url) -> ExtractedProfile` function

The scraper picks the first handler whose `matches` returns True and uses
it before falling back to the generic extractor. Order of registration
matters — more specific handlers should register first (tight domains
before broad patterns).
"""
from __future__ import annotations

from src.connectors.platforms import (
    soundcloud,      # noqa: F401
    github,          # noqa: F401
    twitter,         # noqa: F401
    instagram,       # noqa: F401
    linkedin,        # noqa: F401
    youtube,         # noqa: F401
    reddit,          # noqa: F401
    mastodon,        # noqa: F401
)
