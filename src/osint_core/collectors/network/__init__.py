"""IP address geolocation and metadata collector.

Uses ip-api.com (free, no API key, 45 req/min) to resolve:
  - Country, region, city
  - ISP and organization
  - AS number
  - Latitude / longitude
  - Timezone
  - Proxy / VPN / hosting detection
"""

from __future__ import annotations

import logging
from typing import ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, IpAddress
from osint_core.entities.profiles import Location

log = logging.getLogger(__name__)


class IpLookupCollector(BaseCollector):
    name = "ip_lookup"
    consumes: ClassVar[list[str]] = ["ip"]
    produces: ClassVar[list[str]] = ["location", "domain"]

    async def collect(self, event: EntityDiscovered) -> None:
        ip_entity = event.entity
        if not isinstance(ip_entity, IpAddress):
            return

        ip = ip_entity.value

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"http://ip-api.com/json/{ip}",
                    params={
                        "fields": (
                            "status,message,country,countryCode,region,"
                            "regionName,city,zip,lat,lon,timezone,isp,"
                            "org,as,asname,reverse,mobile,proxy,hosting,query"
                        )
                    },
                )
                data = r.json()
        except Exception as exc:
            self.log.warning("ip-api.com lookup failed for %s: %s", ip, exc)
            return

        if data.get("status") != "success":
            self.log.info("ip-api.com: %s — %s", ip, data.get("message", "failed"))
            ip_entity.metadata["confidence_score"] = 10
            return

        country = data.get("country", "")
        city = data.get("city", "")
        isp = data.get("isp", "")
        org = data.get("org", "")
        as_name = data.get("asname", "")
        as_number = data.get("as", "")
        lat = data.get("lat")
        lon = data.get("lon")
        tz = data.get("timezone", "")
        is_proxy = data.get("proxy", False)
        is_hosting = data.get("hosting", False)
        is_mobile = data.get("mobile", False)
        reverse_dns = data.get("reverse", "")
        region = data.get("regionName", "")
        zipcode = data.get("zip", "")

        # Confidence based on data quality
        confidence = 80
        if is_proxy or is_hosting:
            confidence = 40  # VPN/proxy = location unreliable
        if not city:
            confidence = max(confidence - 20, 20)

        ip_entity.metadata.update({
            "country": country,
            "country_code": data.get("countryCode", ""),
            "region": region,
            "city": city,
            "zip": zipcode,
            "latitude": lat,
            "longitude": lon,
            "timezone": tz,
            "isp": isp,
            "organization": org,
            "as_number": as_number,
            "as_name": as_name,
            "reverse_dns": reverse_dns,
            "is_proxy": is_proxy,
            "is_vpn": is_proxy,
            "is_hosting": is_hosting,
            "is_mobile": is_mobile,
            "confidence_score": confidence,
        })

        self.log.info(
            "IP %s: %s, %s (%s) — ISP: %s — %s (conf=%d%%)",
            ip, city, country, tz, isp,
            "PROXY/VPN" if is_proxy else ("HOSTING" if is_hosting else "residential"),
            confidence,
        )

        # Emit Location
        loc_parts = [p for p in (city, region, country) if p]
        if loc_parts:
            loc = Location(
                value=", ".join(loc_parts),
                city=city or None,
                country=country or None,
                latitude=lat,
                longitude=lon,
                evidence=[
                    Evidence(
                        collector=self.name,
                        confidence=confidence / 100,
                        notes=(
                            f"IP geolocation for {ip} — ISP: {isp}"
                            + (f" (PROXY/VPN detected)" if is_proxy else "")
                            + (f" (hosting provider)" if is_hosting else "")
                        ),
                        raw_data=data,
                    )
                ],
            )
            await self.emit(loc, event)

        # Emit reverse DNS as Domain if available
        if reverse_dns and "." in reverse_dns:
            try:
                domain = Domain(
                    value=reverse_dns,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.90,
                            notes=f"Reverse DNS for {ip}",
                        )
                    ],
                )
                await self.emit(domain, event)
            except ValueError:
                pass
