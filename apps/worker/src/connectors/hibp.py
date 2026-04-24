"""HaveIBeenPwned connector.

HIBP (https://haveibeenpwned.com) lists known data breaches. The breached-
accounts endpoint takes an email and returns every breach it appeared in,
with the breach metadata (site, date, leaked data types).

**Requires an API key.** Free keys exist (the "HIBP Free" tier, $3.95/mo for
the breach API) — without one, this connector is dead and auto-skipped.

Input : DataType.EMAIL
Output: one DataType.OTHER finding per breach (we tag each as
        "breach:<BreachName>"), plus notes listing the leaked data classes.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import (
    ConnectorCategory,
    ConnectorCost,
    DataType,
    HealthStatus,
)

logger = logging.getLogger(__name__)

HIBP_BASE = "https://haveibeenpwned.com/api/v3"


@register
class HibpConnector(BaseConnector):
    name = "hibp"
    display_name = "HaveIBeenPwned — breach exposure"
    category = ConnectorCategory.BREACH
    description = (
        "Queries the HaveIBeenPwned breach database for the submitted email. "
        "Returns every publicly-disclosed breach where the address appeared, "
        "with the date and the types of data leaked. Requires an API key."
    )
    homepage_url = "https://haveibeenpwned.com"
    input_types = {DataType.EMAIL}
    output_types = {DataType.OTHER}
    cost = ConnectorCost.API_KEY_FREE_TIER
    timeout_seconds = 30

    @property
    def _api_key(self) -> str | None:
        return os.getenv("HIBP_API_KEY") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.EMAIL:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        key = self._api_key
        if not key:
            return ConnectorResult(error="HIBP_API_KEY not set — skipping")

        email = input_value.strip().lower()
        if "@" not in email:
            return ConnectorResult(error="Value does not look like an email")

        url = f"{HIBP_BASE}/breachedaccount/{email}?truncateResponse=false"
        headers = {
            "hibp-api-key": key,
            "user-agent": "poireaut/0.5 (+osint-research)",
        }

        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"HIBP HTTP error: {exc}")

        if resp.status_code == 404:
            # Not found = no breaches, not an error
            return ConnectorResult(findings=[], raw_output={"breaches": 0})

        if resp.status_code == 401:
            return ConnectorResult(error="HIBP API key invalid or missing")
        if resp.status_code == 429:
            return ConnectorResult(error="HIBP rate-limited (1 req/1.5s on free tier)")
        if resp.status_code != 200:
            return ConnectorResult(
                error=f"HIBP returned {resp.status_code}: {resp.text[:200]}"
            )

        try:
            breaches: list[dict[str, Any]] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"HIBP response not JSON: {exc}")

        findings: list[Finding] = []
        for b in breaches:
            name = b.get("Name", "unknown")
            domain = b.get("Domain", "")
            breach_date = b.get("BreachDate")  # YYYY-MM-DD
            classes = b.get("DataClasses", []) or []
            extracted_at = _parse_date(breach_date) or now_utc()

            findings.append(
                Finding(
                    data_type=DataType.OTHER,
                    value=f"breach:{name}",
                    confidence=0.95,
                    source_url=f"https://haveibeenpwned.com/PwnedWebsites#{name}",
                    extracted_at=extracted_at,
                    raw=b,
                    notes=(
                        f"Breach of {domain or name} on {breach_date or 'unknown date'}; "
                        f"leaked: {', '.join(classes) if classes else 'unspecified'}"
                    ),
                )
            )

        return ConnectorResult(findings=findings, raw_output={"breaches": len(breaches)})

    async def healthcheck(self) -> HealthStatus:
        if not self._api_key:
            return HealthStatus.DEGRADED  # usable but disabled without key
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # /breaches (listing) is a light endpoint that also requires the key.
                r = await client.get(
                    f"{HIBP_BASE}/breaches",
                    headers={"hibp-api-key": self._api_key},
                )
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        from datetime import timezone
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
