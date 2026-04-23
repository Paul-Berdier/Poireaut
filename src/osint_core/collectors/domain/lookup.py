"""Domain intelligence collector.

For every Domain entity, performs:
  1. DNS MX records → reveals email infrastructure
  2. DNS TXT records → reveals SPF, DMARC, verification tokens
  3. WHOIS via python socket (basic, no external dep) or python-whois if installed
  4. crt.sh API → certificate transparency logs, reveals subdomains
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import ClassVar

import httpx

from osint_core.bus.events import EntityDiscovered
from osint_core.collectors.base import BaseCollector
from osint_core.entities.base import Evidence
from osint_core.entities.identifiers import Domain, Email
from osint_core.entities.profiles import Location

log = logging.getLogger(__name__)


class DomainLookupCollector(BaseCollector):
    name = "domain_lookup"
    consumes: ClassVar[list[str]] = ["domain"]
    produces: ClassVar[list[str]] = ["email", "location"]

    async def collect(self, event: EntityDiscovered) -> None:
        domain = event.entity
        if not isinstance(domain, Domain):
            return
        name = domain.value

        # Skip disposable domains
        if domain.metadata.get("disposable"):
            return

        results: dict = {}

        # 1. DNS resolution
        try:
            dns_data = await asyncio.to_thread(self._dns_lookup, name)
            results.update(dns_data)
        except Exception as exc:
            self.log.debug("DNS failed for %s: %s", name, exc)

        # 2. crt.sh certificate transparency
        try:
            crt_data = await self._crtsh_lookup(name)
            results["certificates"] = crt_data
        except Exception as exc:
            self.log.debug("crt.sh failed for %s: %s", name, exc)

        # 3. WHOIS (try python-whois, fallback to socket)
        try:
            whois_data = await asyncio.to_thread(self._whois_lookup, name)
            results.update(whois_data)
        except Exception as exc:
            self.log.debug("WHOIS failed for %s: %s", name, exc)

        domain.metadata.update(results)
        domain.metadata["confidence_score"] = 90

        self.log.info(
            "domain %s: MX=%s, IPs=%s, certs=%d, registrar=%s",
            name,
            results.get("mx_records", []),
            results.get("a_records", []),
            len(results.get("certificates", [])),
            results.get("registrar", "?"),
        )

        # Emit admin email if found in WHOIS
        admin_email = results.get("registrant_email")
        if admin_email and "@" in admin_email and "privacy" not in admin_email.lower():
            try:
                email = Email(
                    value=admin_email,
                    evidence=[
                        Evidence(
                            collector=self.name,
                            confidence=0.70,
                            notes=f"WHOIS registrant email for {name}",
                        )
                    ],
                )
                await self.emit(email, event)
            except ValueError:
                pass

    def _dns_lookup(self, domain: str) -> dict:
        """Basic DNS lookup using socket (no external deps)."""
        result: dict = {"a_records": [], "mx_records": []}
        try:
            ips = socket.getaddrinfo(domain, None, socket.AF_INET)
            result["a_records"] = list(set(ip[4][0] for ip in ips))
        except socket.gaierror:
            pass

        # MX via DNS resolver if available
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "MX")
            result["mx_records"] = [str(r.exchange).rstrip(".") for r in answers]
        except Exception:
            pass

        # TXT
        try:
            import dns.resolver
            answers = dns.resolver.resolve(domain, "TXT")
            result["txt_records"] = [str(r) for r in answers]
        except Exception:
            pass

        return result

    async def _crtsh_lookup(self, domain: str) -> list[dict]:
        """Query crt.sh for certificate transparency logs."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://crt.sh/?q=%.{domain}&output=json",
                    headers={"User-Agent": "osint-core/0.1"},
                )
                if r.status_code != 200:
                    return []
                data = r.json()
                # Deduplicate by common_name
                seen = set()
                results = []
                for entry in data[:50]:  # limit
                    cn = entry.get("common_name", "")
                    if cn not in seen:
                        seen.add(cn)
                        results.append({
                            "common_name": cn,
                            "issuer": entry.get("issuer_name", ""),
                            "not_before": entry.get("not_before", ""),
                            "not_after": entry.get("not_after", ""),
                        })
                return results
        except Exception:
            return []

    def _whois_lookup(self, domain: str) -> dict:
        """WHOIS lookup — tries python-whois first, then raw socket."""
        try:
            import whois
            w = whois.whois(domain)
            return {
                "registrar": w.registrar or "",
                "creation_date": str(w.creation_date) if w.creation_date else "",
                "expiration_date": str(w.expiration_date) if w.expiration_date else "",
                "registrant_email": (
                    w.emails[0] if isinstance(w.emails, list) and w.emails
                    else (w.emails if isinstance(w.emails, str) else "")
                ),
                "name_servers": w.name_servers or [],
                "whois_source": "python-whois",
            }
        except Exception:
            pass

        # Fallback: raw socket WHOIS
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect(("whois.iana.org", 43))
            s.send(f"{domain}\r\n".encode())
            response = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                response += chunk
            s.close()
            text = response.decode("utf-8", errors="replace")
            result: dict = {"whois_raw": text[:2000], "whois_source": "socket"}
            for line in text.split("\n"):
                low = line.lower().strip()
                if "registrar:" in low:
                    result["registrar"] = line.split(":", 1)[1].strip()
                if "creation date:" in low or "created:" in low:
                    result["creation_date"] = line.split(":", 1)[1].strip()
            return result
        except Exception:
            return {}
