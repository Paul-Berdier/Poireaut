"""Shodan connector.

Shodan indexes the public-facing internet. Given an IP or a domain, it
returns the open ports, the banner of each service, the SSL/TLS cert
details, and known CVEs affecting the discovered software. Indispensable
for cyber-OSINT but overkill for purely social investigations.

Membership is a $69 one-time fee (no recurring) for a developer key with
1 query/sec and 100 results/page. We adapt to both IP and domain inputs;
for a domain we use Shodan's domain search endpoint (`/dns/domain/`).

Input : DataType.IP, DataType.DOMAIN
Output: OTHER (port + service banner), DOMAIN (subdomains discovered)
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
SHODAN_HOST_URL = "https://api.shodan.io/shodan/host/{ip}"
SHODAN_DOMAIN_URL = "https://api.shodan.io/dns/domain/{domain}"


@register
class ShodanConnector(BaseConnector):
    name = "shodan"
    display_name = "Shodan — services exposés sur internet"
    category = ConnectorCategory.IP
    description = (
        "Pour une IP, retourne les ports ouverts et les bannières des "
        "services détectés par Shodan ; pour un domaine, énumère les "
        "sous-domaines et leurs IPs. Nécessite une clé d'API Shodan."
    )
    homepage_url = "https://shodan.io"
    input_types = {DataType.IP, DataType.DOMAIN}
    output_types = {DataType.OTHER, DataType.DOMAIN, DataType.IP}
    cost = ConnectorCost.PAID
    timeout_seconds = 30

    @property
    def _api_key(self) -> str | None:
        return os.getenv("SHODAN_API_KEY") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        key = self._api_key
        if not key:
            return ConnectorResult(error="SHODAN_API_KEY not set — skipping")

        if input_type is DataType.IP:
            return await self._lookup_ip(input_value.strip(), key)
        if input_type is DataType.DOMAIN:
            return await self._lookup_domain(input_value.strip().lower(), key)
        return ConnectorResult(error=f"Unsupported input type: {input_type}")

    async def _lookup_ip(self, ip: str, key: str) -> ConnectorResult:
        params = {"key": key}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(SHODAN_HOST_URL.format(ip=ip), params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Shodan HTTP error: {exc}")

        if resp.status_code == 404:
            return ConnectorResult(findings=[], raw_output={"ip": ip, "indexed": False})
        if resp.status_code != 200:
            return ConnectorResult(error=f"Shodan returned {resp.status_code}")

        try:
            data: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Shodan JSON parse failed: {exc}")

        findings: list[Finding] = []
        src_url = f"https://www.shodan.io/host/{ip}"

        services = data.get("data") or []
        for svc in services if isinstance(services, list) else []:
            port = svc.get("port")
            product = svc.get("product") or svc.get("_shodan", {}).get("module")
            transport = svc.get("transport", "tcp")
            if not port:
                continue
            label = f"{port}/{transport}"
            if product:
                label += f" ({product})"
            cb = build("shodan.port_open", 0.95, "Service détecté actif par Shodan")
            findings.append(Finding(
                data_type=DataType.OTHER,
                value=f"shodan: {label}",
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                raw={"shodan_service": svc, "_signals": cb.to_raw()},
                notes=f"Port {label} ouvert sur {ip}",
            ))

        # Aggregate org + country as one informative OTHER
        org = data.get("org")
        country = data.get("country_name")
        if org or country:
            cb = build("shodan.host_info", 0.9, "Informations hôte Shodan")
            value = " · ".join(p for p in [org, country] if p)
            findings.append(Finding(
                data_type=DataType.OTHER,
                value=f"shodan host: {value}",
                confidence=round(cb.compose(), 2),
                source_url=src_url,
                extracted_at=now_utc(),
                notes=f"Hébergeur / pays selon Shodan",
            ))

        return ConnectorResult(
            findings=findings,
            raw_output={"ip": ip, "ports_count": len(services) if isinstance(services, list) else 0},
        )

    async def _lookup_domain(self, domain: str, key: str) -> ConnectorResult:
        params = {"key": key}
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(SHODAN_DOMAIN_URL.format(domain=domain), params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Shodan HTTP error: {exc}")

        if resp.status_code != 200:
            return ConnectorResult(error=f"Shodan returned {resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Shodan JSON parse failed: {exc}")

        findings: list[Finding] = []
        seen_subs: set[str] = set()
        seen_ips: set[str] = set()

        for entry in data.get("data") or []:
            if not isinstance(entry, dict):
                continue
            subdomain = entry.get("subdomain")
            value = entry.get("value")
            rec_type = entry.get("type")  # A, AAAA, MX, CNAME, …
            if not value:
                continue
            full = f"{subdomain}.{domain}" if subdomain else domain
            if rec_type in ("A", "AAAA") and value not in seen_ips:
                seen_ips.add(value)
                cb = build("shodan.dns_a", 0.95, "Enregistrement DNS Shodan")
                findings.append(Finding(
                    data_type=DataType.IP,
                    value=value,
                    confidence=round(cb.compose(), 2),
                    source_url=f"https://www.shodan.io/domain/{domain}",
                    extracted_at=now_utc(),
                    notes=f"IP de {full}",
                ))
            if subdomain and full not in seen_subs and full != domain:
                seen_subs.add(full)
                cb = build("shodan.subdomain", 0.95, "Sous-domaine listé par Shodan")
                findings.append(Finding(
                    data_type=DataType.DOMAIN,
                    value=full,
                    confidence=round(cb.compose(), 2),
                    source_url=f"https://www.shodan.io/domain/{domain}",
                    extracted_at=now_utc(),
                    notes=f"Sous-domaine de {domain}",
                ))

        return ConnectorResult(
            findings=findings,
            raw_output={"domain": domain, "subdomains": len(seen_subs), "ips": len(seen_ips)},
        )

    async def healthcheck(self) -> HealthStatus:
        if not self._api_key:
            return HealthStatus.DEGRADED
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(
                    "https://api.shodan.io/api-info",
                    params={"key": self._api_key},
                )
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
