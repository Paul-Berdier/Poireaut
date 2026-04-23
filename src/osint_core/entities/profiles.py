"""Higher-level entities built from correlations or enrichment.

- Account: a concrete presence on a specific platform (e.g. github:alice)
- Person: the human being at the center of an investigation
- Location: a geographic point or area
- ImageAsset: a picture found during investigation
"""

from __future__ import annotations

from typing import Literal

from osint_core.entities.base import Entity


class Account(Entity):
    """An account on a specific platform/site.

    The canonical `value` is "<platform>:<username>" to make dedup_key work
    across multiple findings of the same account.
    """

    entity_type: Literal["account"] = "account"
    platform: str = ""
    username: str = ""
    profile_url: str | None = None
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    followers_count: int | None = None
    verified: bool | None = None


class Person(Entity):
    """A human being — the ultimate target of most OSINT investigations.

    We build up a Person by correlating Accounts, Emails, Images, etc.
    """

    entity_type: Literal["person"] = "person"
    full_name: str | None = None
    aliases: list[str] = []
    nationality: str | None = None
    approximate_age: int | None = None


class Organization(Entity):
    """A legal entity — company, association, public body.

    The canonical `value` is the registered/commercial name. Concrete
    identifiers (SIREN/SIRET for France, registration number for other
    jurisdictions) live in `metadata` so we don't couple the graph to
    one jurisdiction's schema.
    """

    entity_type: Literal["organization"] = "organization"
    legal_form: str | None = None
    registration_number: str | None = None  # SIREN, company number, etc.
    jurisdiction: str | None = None  # "FR", "UK", ...
    registered_address: str | None = None
    active: bool | None = None
    created_at: str | None = None  # ISO date if known


class Location(Entity):
    entity_type: Literal["location"] = "location"
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    city: str | None = None
    precision_meters: float | None = None


class ImageAsset(Entity):
    """A picture discovered during investigation.

    The `value` is typically the source URL. Perceptual hash allows
    cross-platform correlation ("this avatar appears on 5 different accounts").
    """

    entity_type: Literal["image"] = "image"
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    perceptual_hash: str | None = None
    exif_gps: tuple[float, float] | None = None  # (lat, lon)
