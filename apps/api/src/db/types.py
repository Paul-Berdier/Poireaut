"""Enums shared between SQLAlchemy models and Pydantic schemas.

Using plain `str, Enum` so Pydantic serializes them as their string value.
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[Enum], *, name: str) -> SAEnum:
    """SQLAlchemy Enum column helper that stores `.value` (not `.name`).

    By default SQLAlchemy's ``Enum`` sends ``member.name`` to the database.
    Our Python members are UPPERCASE (``INVESTIGATOR``) while the Postgres
    enum was declared in lowercase (``'investigator'``). Without
    ``values_callable``, INSERTs fail with::

        invalid input value for enum user_role: "INVESTIGATOR"

    ``values_callable`` makes SQLAlchemy send ``member.value`` instead.
    ``create_type=False`` keeps Alembic in charge of enum lifecycle.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        create_type=False,
        native_enum=True,
    )


class UserRole(str, Enum):
    ADMIN = "admin"
    INVESTIGATOR = "investigator"


class InvestigationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


class EntityRole(str, Enum):
    """Where this entity stands in the investigation."""

    TARGET = "target"       # the primary subject
    RELATED = "related"     # relative, colleague, contact surfaced by pivots


class DataType(str, Enum):
    """Every kind of atomic fact Poireaut can pin on an entity."""

    EMAIL = "email"
    USERNAME = "username"
    PHONE = "phone"
    NAME = "name"
    ADDRESS = "address"
    URL = "url"
    PHOTO = "photo"
    IP = "ip"
    DOMAIN = "domain"
    DATE_OF_BIRTH = "date_of_birth"
    ACCOUNT = "account"        # "has a Twitter account" with URL + handle
    LOCATION = "location"      # GPS / GEOINT
    EMPLOYER = "employer"
    SCHOOL = "school"
    FAMILY = "family"
    OTHER = "other"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VALIDATED = "validated"
    REJECTED = "rejected"


class ConnectorCategory(str, Enum):
    EMAIL = "email"
    USERNAME = "username"
    PHONE = "phone"
    IMAGE = "image"
    DOMAIN = "domain"
    IP = "ip"
    BREACH = "breach"
    PEOPLE = "people"
    COMPANY = "company"
    SOCMINT = "socmint"
    GEOINT = "geoint"
    ARCHIVE = "archive"
    OTHER = "other"


class ConnectorCost(str, Enum):
    FREE = "free"
    API_KEY_FREE_TIER = "api_key_free_tier"
    PAID = "paid"


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DEAD = "dead"
    UNKNOWN = "unknown"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
