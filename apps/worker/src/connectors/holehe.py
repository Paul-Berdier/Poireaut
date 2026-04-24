"""Holehe connector with active verification.

Holehe uses forgotten-password flows to detect whether an email is registered
on ~120 platforms. Without verification, its findings are "the site behaves as
if this email has an account here" — useful but probabilistic. We upgrade it
by *actually HEAD-ing the public profile URL* for each hit, producing a
confidence score grounded in real HTTP responses.

Input : DataType.EMAIL
Output: one DataType.ACCOUNT finding per site where the email exists.
        `confidence` field reflects the verification verdict.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

import httpx

from src.connectors._verify import verify_many
from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)


@register
class HoleheConnector(BaseConnector):
    name = "holehe"
    display_name = "Holehe — email account discovery"
    category = ConnectorCategory.EMAIL
    description = (
        "Probes ~120 popular sites to see whether the supplied email address "
        "has an account there. Each hit is then actively re-checked against "
        "the site's public profile URL to score confidence."
    )
    homepage_url = "https://github.com/megadose/holehe"
    input_types = {DataType.EMAIL}
    output_types = {DataType.ACCOUNT}
    timeout_seconds = 90

    def _discover_modules(self) -> list:
        try:
            from holehe import modules as holehe_modules
        except ImportError:
            return []
        funcs = []
        for _finder, mod_name, is_pkg in pkgutil.walk_packages(
            holehe_modules.__path__, prefix="holehe.modules."
        ):
            if is_pkg:
                continue
            try:
                module = importlib.import_module(mod_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping holehe module %s: %s", mod_name, exc)
                continue
            leaf = mod_name.rsplit(".", 1)[1]
            fn = getattr(module, leaf, None)
            if callable(fn):
                funcs.append((leaf, fn))
        return funcs

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.EMAIL:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        email = input_value.strip().lower()
        if "@" not in email:
            return ConnectorResult(error="Value does not look like an email")

        modules = self._discover_modules()
        if not modules:
            return ConnectorResult(error="Holehe library not installed")

        raw_hits: list[dict[str, Any]] = []
        errors: list[str] = []

        # Phase 1 — run Holehe's default probe
        async with httpx.AsyncClient(
            timeout=8.0,
            headers={"User-Agent": "Mozilla/5.0 (poireaut)"},
        ) as client:
            for site_name, fn in modules:
                out: list[dict[str, Any]] = []
                try:
                    await fn(email, client, out)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{site_name}: {type(exc).__name__}")
                    continue
                for entry in out:
                    if entry.get("exists"):
                        entry["_site"] = site_name
                        raw_hits.append(entry)

        # Phase 2 — actively verify every hit that has a usable URL
        verify_pairs: list[tuple[str, str | None]] = []
        for entry in raw_hits:
            domain = entry.get("domain") or entry["_site"]
            url = _best_url_for(domain)
            if url:
                entry["_profile_url"] = url
                verify_pairs.append((url, None))

        verifications = await verify_many(verify_pairs, concurrency=10) if verify_pairs else {}

        # Phase 3 — shape findings
        findings: list[Finding] = []
        for entry in raw_hits:
            domain = entry.get("domain") or entry["_site"]
            rate_limited = bool(entry.get("rateLimit"))
            profile_url = entry.get("_profile_url")

            # Base confidence from Holehe's own signal
            base_conf = 0.55 if rate_limited else 0.75

            verdict = None
            verify_reason = None
            if profile_url and profile_url in verifications:
                v = verifications[profile_url]
                verdict = v.verdict
                verify_reason = v.reason
                # Combine: URL check dominates when it's confident either way
                if v.verdict == "confirmed":
                    conf = max(base_conf, v.confidence)
                elif v.verdict == "missing":
                    # Holehe lied or the profile page is behind a login wall.
                    # Keep the hit but drop confidence low.
                    conf = 0.25
                elif v.verdict == "unreachable":
                    conf = max(0.4, base_conf - 0.2)
                else:  # uncertain
                    conf = (base_conf + v.confidence) / 2
            else:
                conf = base_conf

            notes_parts = [f"Holehe: compte détecté sur {domain}"]
            if rate_limited:
                notes_parts.append("site rate-limité (confiance réduite)")
            if verify_reason:
                notes_parts.append(f"vérif URL: {verify_reason}")

            findings.append(
                Finding(
                    data_type=DataType.ACCOUNT,
                    value=domain,
                    confidence=round(conf, 2),
                    source_url=profile_url,
                    extracted_at=now_utc(),
                    raw={
                        "holehe": entry,
                        "verification": verdict,
                        "verification_reason": verify_reason,
                    },
                    notes=" · ".join(notes_parts),
                )
            )

        raw_out = {
            "modules_total": len(modules),
            "probe_errors": errors[:20],
            "verified": sum(
                1 for v in verifications.values() if v.verdict == "confirmed"
            ),
            "verification_checked": len(verifications),
        }
        return ConnectorResult(findings=findings, raw_output=raw_out)

    def _healthcheck_probe(self) -> tuple[str, DataType] | None:
        return None

    async def healthcheck(self):
        try:
            import holehe.modules  # noqa: F401
            return HealthStatus.OK
        except ImportError:
            return HealthStatus.DEAD


def _best_url_for(domain: str) -> str | None:
    if not domain:
        return None
    if domain.startswith("http"):
        return domain
    return f"https://{domain.lstrip('.')}"
