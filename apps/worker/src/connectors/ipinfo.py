"""IPInfo connector.

IPInfo.io is the standard free-tier IP geolocation provider. Free plan
gives 50k requests/month, which is more than enough for normal Poireaut
usage. With an API key, you get country, region, city, postal code,
timezone, ASN, organisation, and a privacy flag (vpn/proxy/tor).

Without a key, the API still works but is rate-limited to 1000 req/day
and returns less data. So the connector adapts based on env presence.

Input : DataType.IP
Output: ADDRESS (geo), OTHER (org / ASN), DOMAIN (rDNS hostname)
"""
from __future__ import annotations

import ipaddress
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
IPINFO_URL = "https://ipinfo.io/{ip}/json"


@register
class IpInfoConnector(BaseConnector):
    name = "ipinfo"
    display_name = "IPInfo — IP géolocalisation + organisation"
    category = ConnectorCategory.IP
    description = (
        "Géolocalise une adresse IP : pays, région, ville, fuseau, ASN, "
        "organisation, et drapeau VPN/proxy/Tor. Gratuit jusqu'à 50k "
        "requêtes/mois avec une clé d'API ; fonctionne aussi sans clé "
        "(rate-limit plus strict)."
    )
    homepage_url = "https://ipinfo.io"
    input_types = {DataType.IP}
    output_types = {DataType.ADDRESS, DataType.OTHER, DataType.DOMAIN}
    cost = ConnectorCost.API_KEY_FREE_TIER
    timeout_seconds = 15

    @property
    def _api_key(self) -> str | None:
        return os.getenv("IPINFO_API_KEY") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.IP:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        ip = input_value.strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return ConnectorResult(error=f"Not a valid IP address: {ip!r}")

        params = {"token": self._api_key} if self._api_key else {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(IPINFO_URL.format(ip=ip), params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"IPInfo HTTP error: {exc}")

        if resp.status_code != 200:
            return ConnectorResult(
                error=f"IPInfo returned {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"IPInfo response not JSON: {exc}")

        findings: list[Finding] = []
        src_url = f"https://ipinfo.io/{ip}"

        # Geoloc → ADDRESS
        city = data.get("city")
        region = data.get("region")
        country = data.get("country")
        postal = data.get("postal")
        loc = data.get("loc")  # "lat,lon"
        if city or region or country:
            parts = [p for p in [city, region, postal, country] if p]
            address_value = ", ".join(parts)
            cb = build("ipinfo.geoloc", 0.85, "Géolocalisation IPInfo")
            if loc:
                cb.add("ipinfo.with_coords", 0.05, f"Coordonnées GPS: {loc}")
            findings.append(Finding(
                data_type=DataType.ADDRESS,
                value=address_value,
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                raw={**data, "_signals": cb.to_raw()},
                notes=f"IP {ip} géolocalisée via IPInfo" + (f" · GPS {loc}" if loc else ""),
            ))

        # Org / ASN → OTHER
        org = data.get("org")
        if org:
            cb = build("ipinfo.org_lookup", 0.9, "Organisation déclarée par IPInfo")
            findings.append(Finding(
                data_type=DataType.OTHER,
                value=f"org: {org}",
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                raw={"asn_or_org": org, "_signals": cb.to_raw()},
                notes=f"Opérateur / hébergeur de {ip}",
            ))

        # Reverse DNS → DOMAIN (interesting for pivoting)
        hostname = data.get("hostname")
        if hostname:
            cb = build("ipinfo.rdns", 0.8, "Reverse DNS confirmé")
            findings.append(Finding(
                data_type=DataType.DOMAIN,
                value=hostname,
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                raw={"_signals": cb.to_raw()},
                notes=f"PTR record de {ip}",
            ))

        # Privacy flag (free tier doesn't include this, paid does)
        privacy = data.get("privacy") or {}
        if isinstance(privacy, dict):
            tags = [k for k, v in privacy.items() if v]
            if tags:
                cb = build("ipinfo.privacy_flag", 0.95, "Drapeau de réseau anonymisant")
                findings.append(Finding(
                    data_type=DataType.OTHER,
                    value=f"network: {', '.join(tags)}",
                    confidence=round(cb.compose(), 2),
                    source_url=src_url,
                    extracted_at=now_utc(),
                    notes=f"⚠️ IP {ip} marquée comme : {', '.join(tags)}",
                ))

        return ConnectorResult(
            findings=findings,
            raw_output={"ip": ip, "has_api_key": bool(self._api_key)},
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                params = {"token": self._api_key} if self._api_key else {}
                r = await c.get(IPINFO_URL.format(ip="8.8.8.8"), params=params)
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
