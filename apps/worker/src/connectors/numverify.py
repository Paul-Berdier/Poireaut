"""Numverify connector.

Numverify is an API by APILayer that validates a phone number and returns
its country, line type (mobile/landline), carrier, and an international
canonical form. Free tier: 250 req/mo. Paid: $20/mo for 5k.

This is the standard "I have a phone number, who is it?" enrichment.
Combined with IPInfo (for VOIP traceback) and Hunter (for cross-ref
with email/business databases), it makes phone numbers actionable.

Input : DataType.PHONE
Output: ADDRESS (country/region), OTHER (carrier, line type)
"""
from __future__ import annotations

import logging
import os
import re
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
NUMVERIFY_URL = "http://apilayer.net/api/validate"


@register
class NumverifyConnector(BaseConnector):
    name = "numverify"
    display_name = "Numverify — validation et enrichissement téléphone"
    category = ConnectorCategory.PHONE
    description = (
        "Valide un numéro de téléphone international et renvoie son pays, "
        "type de ligne (mobile/fixe), opérateur. Nécessite une clé d'API "
        "Numverify (250 req/mo gratuit, 5k pour 20$/mois)."
    )
    homepage_url = "https://numverify.com"
    input_types = {DataType.PHONE}
    output_types = {DataType.ADDRESS, DataType.OTHER}
    cost = ConnectorCost.API_KEY_FREE_TIER
    timeout_seconds = 15

    @property
    def _api_key(self) -> str | None:
        return os.getenv("NUMVERIFY_API_KEY") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.PHONE:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        key = self._api_key
        if not key:
            return ConnectorResult(error="NUMVERIFY_API_KEY not set — skipping")

        # Numverify accepts E.164-ish format. We strip non-digits keeping a leading +.
        phone = input_value.strip()
        cleaned = re.sub(r"[^\d+]", "", phone)
        if not cleaned:
            return ConnectorResult(error="Phone number contains no digits")

        params = {"access_key": key, "number": cleaned}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(NUMVERIFY_URL, params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Numverify HTTP error: {exc}")

        if resp.status_code != 200:
            return ConnectorResult(
                error=f"Numverify returned {resp.status_code}"
            )

        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Numverify response not JSON: {exc}")

        # Numverify returns {"success": false, "error": {...}} on failure
        if data.get("success") is False:
            err = data.get("error", {})
            return ConnectorResult(
                error=f"Numverify error: {err.get('info', err)}"
            )

        if not data.get("valid"):
            return ConnectorResult(
                findings=[],
                raw_output={"phone": cleaned, "valid": False, "raw": data},
            )

        findings: list[Finding] = []
        country = data.get("country_name")
        country_code = data.get("country_prefix")
        location = data.get("location")
        carrier = data.get("carrier")
        line_type = data.get("line_type")

        # Country/location → ADDRESS
        if country:
            address_parts = [p for p in [location, country] if p]
            cb = build("numverify.country", 0.95,
                       f"Validation E.164 par Numverify ({country_code or '?'})")
            findings.append(Finding(
                data_type=DataType.ADDRESS,
                value=", ".join(address_parts),
                confidence=round(cb.compose(), 2),
                source_url="https://numverify.com",
                extracted_at=now_utc(),
                raw={**data, "_signals": cb.to_raw()},
                notes=f"Pays d'origine du numéro : {country}",
            ))

        # Carrier / line type → OTHER
        if carrier:
            cb = build("numverify.carrier", 0.9,
                       "Opérateur fourni par Numverify")
            findings.append(Finding(
                data_type=DataType.OTHER,
                value=f"carrier: {carrier}" + (f" ({line_type})" if line_type else ""),
                confidence=round(cb.compose(), 2),
                source_url="https://numverify.com",
                extracted_at=now_utc(),
                notes=f"Opérateur {carrier}" + (f" · ligne {line_type}" if line_type else ""),
            ))

        return ConnectorResult(
            findings=findings,
            raw_output={"phone": cleaned, "valid": True},
        )

    async def healthcheck(self) -> HealthStatus:
        if not self._api_key:
            return HealthStatus.DEGRADED
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(NUMVERIFY_URL, params={
                    "access_key": self._api_key, "number": "14158586273",
                })
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
