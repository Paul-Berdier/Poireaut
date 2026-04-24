"""crt.sh connector.

crt.sh (https://crt.sh) exposes the Certificate Transparency logs as a
searchable database. Given a domain, it returns every SSL/TLS cert ever
issued for it or its subdomains. From that we extract a de-duplicated list
of hostnames — a goldmine for surface-area mapping.

Input : DataType.DOMAIN
Output: one DataType.DOMAIN finding per unique subdomain discovered.
        The original domain is skipped.

Entirely free, no auth, no rate limits that we've ever hit in practice.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)

CRTSH_URL = "https://crt.sh/"


@register
class CrtShConnector(BaseConnector):
    name = "crtsh"
    display_name = "crt.sh — subdomain enumeration via CT logs"
    category = ConnectorCategory.DOMAIN
    description = (
        "Queries the public Certificate Transparency logs via crt.sh for "
        "every cert issued to the domain, then extracts all unique "
        "subdomains seen. Free, fast, no rate limits."
    )
    homepage_url = "https://crt.sh"
    input_types = {DataType.DOMAIN}
    output_types = {DataType.DOMAIN}
    timeout_seconds = 45

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.DOMAIN:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        domain = input_value.strip().lower().lstrip("*.")
        if not domain or "." not in domain:
            return ConnectorResult(error="Value does not look like a domain")

        params = {"q": f"%.{domain}", "output": "json"}
        try:
            async with httpx.AsyncClient(
                timeout=30,
                headers={"user-agent": "poireaut/0.5 (+osint-research)"},
            ) as client:
                resp = await client.get(CRTSH_URL, params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"crt.sh HTTP error: {exc}")

        if resp.status_code != 200:
            return ConnectorResult(error=f"crt.sh returned {resp.status_code}")

        try:
            rows: list[dict[str, Any]] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"crt.sh response not JSON: {exc}")

        # Each row may have multiple names in name_value, newline-separated.
        seen: set[str] = set()
        for row in rows:
            names = (row.get("name_value") or "").splitlines()
            for name in names:
                name = name.strip().lower().lstrip("*.")
                if not name:
                    continue
                if name == domain:
                    continue
                if not name.endswith(f".{domain}"):
                    continue
                seen.add(name)

        findings = [
            Finding(
                data_type=DataType.DOMAIN,
                value=sub,
                confidence=0.8,
                source_url=f"https://crt.sh/?q={sub}",
                extracted_at=now_utc(),
            )
            for sub in sorted(seen)
        ]

        return ConnectorResult(
            findings=findings,
            raw_output={"cert_records": len(rows), "unique_subdomains": len(findings)},
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(CRTSH_URL, params={"q": "example.com", "output": "json"})
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
