"""Hunter.io connector.

Hunter.io's email-finder + verifier API turns an email address into:
  - the person's full name (if Hunter has indexed it)
  - their job title (if known)
  - the company name + domain
  - public sources where Hunter found that email

It's the "B2B OSINT" gold standard. 25 free searches/mo, then $49/mo for
500 searches. Without a key the connector stays disabled.

Input : DataType.EMAIL
Output: NAME (person), OTHER (job title), DOMAIN (company), EMPLOYER
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.connectors._signals import build
from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
)

logger = logging.getLogger(__name__)
HUNTER_URL = "https://api.hunter.io/v2/email-verifier"


@register
class HunterConnector(BaseConnector):
    name = "hunter"
    display_name = "Hunter.io — email → personne/entreprise"
    category = ConnectorCategory.PEOPLE
    description = (
        "Pour un email donné, retourne la personne associée (nom complet, "
        "poste), l'entreprise et le domaine, plus les sources publiques où "
        "Hunter a vu cet email. Nécessite une clé d'API (25 req/mo gratuit)."
    )
    homepage_url = "https://hunter.io"
    input_types = {DataType.EMAIL}
    output_types = {DataType.NAME, DataType.OTHER, DataType.DOMAIN, DataType.EMPLOYER}
    cost = ConnectorCost.API_KEY_FREE_TIER
    timeout_seconds = 20

    @property
    def _api_key(self) -> str | None:
        return os.getenv("HUNTER_API_KEY") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.EMAIL:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        key = self._api_key
        if not key:
            return ConnectorResult(error="HUNTER_API_KEY not set — skipping")

        email = input_value.strip().lower()
        if "@" not in email:
            return ConnectorResult(error="Not an email")

        params = {"email": email, "api_key": key}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(HUNTER_URL, params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Hunter HTTP error: {exc}")

        if resp.status_code == 401:
            return ConnectorResult(error="Hunter API key invalid")
        if resp.status_code == 429:
            return ConnectorResult(error="Hunter rate-limited")
        if resp.status_code != 200:
            return ConnectorResult(
                error=f"Hunter returned {resp.status_code}: {resp.text[:200]}"
            )

        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Hunter response not JSON: {exc}")

        data: dict[str, Any] = body.get("data") or {}
        if not data:
            return ConnectorResult(findings=[], raw_output={"empty": True})

        findings: list[Finding] = []
        src_url = "https://hunter.io"

        first = data.get("first_name")
        last = data.get("last_name")
        if first or last:
            full = " ".join(p for p in [first, last] if p).strip()
            cb = build("hunter.name", 0.85,
                       f"Hunter.io a associé un nom à cet email")
            # Score de Hunter (0-100) → bonus
            score = data.get("score")
            if isinstance(score, (int, float)):
                cb.add("hunter.api_score", min(0.1, score / 1000),
                       f"Score Hunter {score}/100")
            findings.append(Finding(
                data_type=DataType.NAME,
                value=full,
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                raw={**data, "_signals": cb.to_raw()},
                notes=f"Nom associé à {email} par Hunter.io",
            ))

        position = data.get("position")
        if position:
            cb = build("hunter.position", 0.85, "Poste fourni par Hunter.io")
            findings.append(Finding(
                data_type=DataType.OTHER,
                value=f"position: {position}",
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                notes=f"Poste de la personne",
            ))

        company = data.get("company")
        if company:
            cb = build("hunter.employer", 0.9, "Employeur identifié")
            findings.append(Finding(
                data_type=DataType.EMPLOYER,
                value=company,
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                notes=f"Entreprise associée à {email}",
            ))

        # The domain part of the email is also often a corporate domain we
        # should pivot on.
        domain = email.split("@", 1)[1] if "@" in email else None
        if domain:
            cb = build("hunter.domain_from_email", 0.95,
                       "Domaine corporate déduit de l'email")
            findings.append(Finding(
                data_type=DataType.DOMAIN,
                value=domain,
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                notes=f"Domaine de {email}",
            ))

        return ConnectorResult(findings=findings, raw_output={"email": email})

    async def healthcheck(self) -> HealthStatus:
        if not self._api_key:
            return HealthStatus.DEGRADED
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(
                    HUNTER_URL,
                    params={"email": "test@hunter.io", "api_key": self._api_key},
                )
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
