"""Atomic identifier entities.

These are the "raw" inputs an investigator starts with or discovers:
usernames, emails, phone numbers, domains, IPs, URLs.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import field_validator

from osint_core.entities.base import Entity


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class Username(Entity):
    entity_type: Literal["username"] = "username"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be empty")
        # Do NOT lowercase: some platforms are case-sensitive, and stylometry
        # sometimes cares about the original casing. We lowercase only in dedup_key.
        return v


class Email(Entity):
    entity_type: Literal["email"] = "email"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError(f"Invalid email format: {v}")
        return v

    @property
    def local_part(self) -> str:
        return self.value.split("@", 1)[0]

    @property
    def domain_part(self) -> str:
        return self.value.split("@", 1)[1]


class Phone(Entity):
    """E.164-normalized phone number if possible, else best effort."""

    entity_type: Literal["phone"] = "phone"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        # Strip everything except digits and leading '+'
        v = v.strip()
        cleaned = "+" + re.sub(r"\D", "", v) if v.startswith("+") else re.sub(r"\D", "", v)
        if len(re.sub(r"\D", "", cleaned)) < 6:
            raise ValueError(f"Phone number too short: {v}")
        return cleaned


class Domain(Entity):
    entity_type: Literal["domain"] = "domain"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().lower().removeprefix("http://").removeprefix("https://")
        v = v.split("/", 1)[0]  # drop path
        v = v.removeprefix("www.")
        if not _DOMAIN_RE.match(v):
            raise ValueError(f"Invalid domain: {v}")
        return v


class Url(Entity):
    entity_type: Literal["url"] = "url"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(f"URL must start with http:// or https://: {v}")
        return v


class IpAddress(Entity):
    entity_type: Literal["ip"] = "ip"

    @field_validator("value")
    @classmethod
    def _normalize(cls, v: str) -> str:
        import ipaddress

        try:
            return str(ipaddress.ip_address(v.strip()))
        except ValueError as e:
            raise ValueError(f"Invalid IP: {v}") from e
