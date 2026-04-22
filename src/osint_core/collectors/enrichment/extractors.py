"""Text extractors — pluggable modules that find entities in free-text bios.

Each extractor is a small, focused class with one job: scan a string,
yield candidate entities with per-match confidence. Extractors don't
know about the bus or the fetcher — they're pure functions of text.
That makes them trivially testable.

Adding a new extractor:
    class MyExtractor(Extractor):
        name = "my_thing"
        def extract(self, text, context):
            yield MyEntity(value=...), 0.7

Then register it in ProfileEnrichmentCollector's `extractors` list.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from osint_core.entities.base import Entity
from osint_core.entities.identifiers import Email, Url, Username
from osint_core.entities.profiles import Location


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Real-world email matcher. Deliberately simpler than RFC 5322 — false negatives
# on exotic addresses are acceptable; false positives cost more.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")

# URL matcher. Strips common trailing punctuation at use-site.
_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

# @handle mentions — 2-30 chars, word boundary before @ to avoid emails.
_HANDLE_RE = re.compile(r"(?:(?<=^)|(?<=[\s,;:!?|]))@([A-Za-z0-9_]{2,30})")

_TRAILING_PUNCT = ".,;:!?)\"'>"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Extractor(ABC):
    """Base class for text-to-entity extractors."""

    name: str = "unnamed"

    @abstractmethod
    def extract(
        self, text: str, context: dict[str, Any]
    ) -> Iterable[tuple[Entity, float]]:
        """Yield (entity, confidence) tuples for each candidate found."""


# ---------------------------------------------------------------------------
# Concrete extractors
# ---------------------------------------------------------------------------


class EmailExtractor(Extractor):
    name = "email"

    def extract(self, text: str, context: dict[str, Any]):
        seen: set[str] = set()
        for raw in _EMAIL_RE.findall(text):
            candidate = raw.strip().lower()
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                yield Email(value=candidate), 0.80
            except ValueError:
                continue


class UrlExtractor(Extractor):
    name = "url"

    def extract(self, text: str, context: dict[str, Any]):
        profile_url = (context.get("profile_url") or "").rstrip("/")
        seen: set[str] = set()
        for raw in _URL_RE.findall(text):
            url = raw.rstrip(_TRAILING_PUNCT)
            if not url or url.rstrip("/") == profile_url:
                continue
            if url in seen:
                continue
            seen.add(url)
            try:
                yield Url(value=url), 0.85
            except ValueError:
                continue


class HandleExtractor(Extractor):
    """Extract @username mentions.

    These are intentionally LOW confidence: "@react" in a bio is probably
    not a handle to follow. Downstream collectors should filter before
    chaining further work on them.
    """

    name = "handle"
    _IGNORE = frozenset(
        {"me", "you", "us", "them", "all", "home", "work", "admin", "team", "react", "vue"}
    )

    def extract(self, text: str, context: dict[str, Any]):
        seen: set[str] = set()
        origin_username = (context.get("username") or "").lower()
        for handle in _HANDLE_RE.findall(text):
            key = handle.lower()
            if key in seen or key == origin_username or key in self._IGNORE:
                continue
            seen.add(key)
            try:
                yield Username(value=handle), 0.40
            except ValueError:
                continue


class LocationExtractor(Extractor):
    """Gazetteer-based location extractor.

    This is a minimal substitute for a proper NER pipeline. It matches
    against a curated list of major cities/countries (case-insensitive,
    word-boundary). For real investigations, swap in a spaCy or transformer
    NER model — the extractor interface is the same.
    """

    name = "location"

    DEFAULT_GAZETTEER: dict[str, dict[str, str]] = {
        # Europe
        "Paris": {"city": "Paris", "country": "FR"},
        "Lyon": {"city": "Lyon", "country": "FR"},
        "Marseille": {"city": "Marseille", "country": "FR"},
        "Toulouse": {"city": "Toulouse", "country": "FR"},
        "Bordeaux": {"city": "Bordeaux", "country": "FR"},
        "Nantes": {"city": "Nantes", "country": "FR"},
        "Lille": {"city": "Lille", "country": "FR"},
        "London": {"city": "London", "country": "UK"},
        "Manchester": {"city": "Manchester", "country": "UK"},
        "Edinburgh": {"city": "Edinburgh", "country": "UK"},
        "Berlin": {"city": "Berlin", "country": "DE"},
        "Munich": {"city": "Munich", "country": "DE"},
        "Hamburg": {"city": "Hamburg", "country": "DE"},
        "Madrid": {"city": "Madrid", "country": "ES"},
        "Barcelona": {"city": "Barcelona", "country": "ES"},
        "Rome": {"city": "Rome", "country": "IT"},
        "Milan": {"city": "Milan", "country": "IT"},
        "Amsterdam": {"city": "Amsterdam", "country": "NL"},
        "Brussels": {"city": "Brussels", "country": "BE"},
        "Zurich": {"city": "Zurich", "country": "CH"},
        "Geneva": {"city": "Geneva", "country": "CH"},
        "Vienna": {"city": "Vienna", "country": "AT"},
        "Stockholm": {"city": "Stockholm", "country": "SE"},
        "Copenhagen": {"city": "Copenhagen", "country": "DK"},
        "Oslo": {"city": "Oslo", "country": "NO"},
        "Helsinki": {"city": "Helsinki", "country": "FI"},
        "Warsaw": {"city": "Warsaw", "country": "PL"},
        "Prague": {"city": "Prague", "country": "CZ"},
        "Lisbon": {"city": "Lisbon", "country": "PT"},
        "Dublin": {"city": "Dublin", "country": "IE"},
        # Americas
        "New York": {"city": "New York", "country": "US"},
        "San Francisco": {"city": "San Francisco", "country": "US"},
        "Los Angeles": {"city": "Los Angeles", "country": "US"},
        "Seattle": {"city": "Seattle", "country": "US"},
        "Boston": {"city": "Boston", "country": "US"},
        "Chicago": {"city": "Chicago", "country": "US"},
        "Austin": {"city": "Austin", "country": "US"},
        "Miami": {"city": "Miami", "country": "US"},
        "Toronto": {"city": "Toronto", "country": "CA"},
        "Montreal": {"city": "Montreal", "country": "CA"},
        "Vancouver": {"city": "Vancouver", "country": "CA"},
        "Mexico City": {"city": "Mexico City", "country": "MX"},
        "São Paulo": {"city": "São Paulo", "country": "BR"},
        "Buenos Aires": {"city": "Buenos Aires", "country": "AR"},
        # Asia-Pacific
        "Tokyo": {"city": "Tokyo", "country": "JP"},
        "Osaka": {"city": "Osaka", "country": "JP"},
        "Seoul": {"city": "Seoul", "country": "KR"},
        "Singapore": {"city": "Singapore", "country": "SG"},
        "Hong Kong": {"city": "Hong Kong", "country": "HK"},
        "Shanghai": {"city": "Shanghai", "country": "CN"},
        "Beijing": {"city": "Beijing", "country": "CN"},
        "Bangalore": {"city": "Bangalore", "country": "IN"},
        "Mumbai": {"city": "Mumbai", "country": "IN"},
        "Delhi": {"city": "Delhi", "country": "IN"},
        "Sydney": {"city": "Sydney", "country": "AU"},
        "Melbourne": {"city": "Melbourne", "country": "AU"},
        "Tel Aviv": {"city": "Tel Aviv", "country": "IL"},
        "Dubai": {"city": "Dubai", "country": "AE"},
    }

    def __init__(self, gazetteer: dict[str, dict[str, str]] | None = None) -> None:
        self.gazetteer = gazetteer if gazetteer is not None else self.DEFAULT_GAZETTEER
        # Precompile a single alternation regex for speed.
        names = sorted(self.gazetteer.keys(), key=len, reverse=True)
        self._pattern = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in names) + r")\b",
            re.IGNORECASE,
        )
        self._lookup = {k.lower(): (k, v) for k, v in self.gazetteer.items()}

    def extract(self, text: str, context: dict[str, Any]):
        seen: set[str] = set()
        for match in self._pattern.finditer(text):
            raw = match.group(1)
            key = raw.lower()
            if key in seen:
                continue
            seen.add(key)
            canonical_name, meta = self._lookup[key]
            yield (
                Location(
                    value=canonical_name,
                    city=meta.get("city"),
                    country=meta.get("country"),
                ),
                0.55,
            )


# Default suite used by ProfileEnrichmentCollector when none is specified.
DEFAULT_EXTRACTORS: list[Extractor] = [
    EmailExtractor(),
    UrlExtractor(),
    HandleExtractor(),
    LocationExtractor(),
]
