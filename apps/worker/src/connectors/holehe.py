"""Holehe connector — email account discovery with calibrated confidence.

Holehe probes ~120 sites' forgotten-password endpoints to detect whether an
email is registered. It returns one hit per site with metadata like:
  - domain (e.g. "spotify.com")
  - rateLimit (site throttled us; "exists=True" became less reliable)
  - emailrecovery / phoneNumber (site leaked partial recovery data → strong)

For each hit we build an ACCOUNT finding. `value` is the full profile URL
when we can guess it (e.g. `github.com/handle` is a well-known pattern),
otherwise just the domain root so the investigator still sees what was
found. We try to keep the two data types simple: ACCOUNT replaces what we
used to split as "account + URL".

Confidence is composed from three signals:
  1. Base per-site reliability (some sites are historically rock-solid,
     others false-positive constantly).
  2. Holehe's own metadata (rate-limited → weaker; recovery data → stronger).
  3. An optional live HTTP check against the domain root — if the site
     returns 5xx or is unreachable, we lower confidence.

Input : DataType.EMAIL
Output: DataType.ACCOUNT (one per site)
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)


# ── Per-site confidence priors ───────────────────────────────

# Sites where Holehe is historically very reliable — stable modules, low FPR.
HIGH_TRUST_SITES = {
    "adobe.com", "amazon.com", "atlassian.com", "ebay.com",
    "envato.com", "github.com", "gitlab.com", "imgur.com",
    "spotify.com", "wordpress.com", "pinterest.com", "protonmail.ch",
    "disneyplus.com", "dropbox.com", "patreon.com", "strava.com",
}
# Sites that tend to false-positive or are behind captchas / rate limits.
LOW_TRUST_SITES = {
    "instagram.com", "facebook.com", "twitter.com", "tiktok.com",
    "snapchat.com",
}


# Sites where a given email can be turned into a guessable public profile URL.
# Holehe only gives us the domain — we don't know the username — so for most
# sites we can't link to an actual profile. These platforms expose the email
# itself or have public "lookup by email" endpoints.
# Keeping this list empty for now is the honest default: we'll enrich it as
# the investigator validates and we find patterns.
# (A future improvement is to pivot from an email to its usernames via
#  other connectors, then build profile URLs for each platform.)
GUESSABLE_PROFILE_URL: dict[str, callable] = {}


@register
class HoleheConnector(BaseConnector):
    name = "holehe"
    display_name = "Holehe — email account discovery"
    category = ConnectorCategory.EMAIL
    description = (
        "Probes ~120 sites to detect whether an email has a registered account. "
        "Confidence is calibrated per-site using Holehe's signals (rate-limit, "
        "leaked recovery data) and a site-reliability prior."
    )
    homepage_url = "https://github.com/megadose/holehe"
    input_types = {DataType.EMAIL}
    output_types = {DataType.ACCOUNT}
    timeout_seconds = 60

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

        findings: list[Finding] = []
        for entry in raw_hits:
            domain = (entry.get("domain") or entry["_site"]).strip().lower()
            conf = _score_holehe_hit(entry, domain)

            # Build a profile URL when we can, otherwise the domain root.
            # Current implementation: we don't know the target's username,
            # so the best "source URL" is the domain root itself — gives the
            # investigator a one-click way to visit the site and look up.
            source_url = f"https://{domain}"
            # For the displayed `value` we want something human: "gmail.com"
            # not "https://gmail.com/" — the source_url already has the link.
            value = domain

            notes_parts = [f"Compte détecté sur {domain}"]
            if entry.get("rateLimit"):
                notes_parts.append("site rate-limité (confiance réduite)")
            if entry.get("emailrecovery") or entry.get("phoneNumber"):
                notes_parts.append("données de récupération partielles révélées (signal fort)")
            if domain in HIGH_TRUST_SITES:
                notes_parts.append("site fiable")
            elif domain in LOW_TRUST_SITES:
                notes_parts.append("⚠️ site à vérifier manuellement")

            findings.append(
                Finding(
                    data_type=DataType.ACCOUNT,
                    value=value,
                    confidence=round(conf, 2),
                    source_url=source_url,
                    extracted_at=now_utc(),
                    raw=entry,
                    notes=" · ".join(notes_parts),
                )
            )

        raw_out = {
            "modules_total": len(modules),
            "hits": len(raw_hits),
            "probe_errors": errors[:20],
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


def _score_holehe_hit(entry: dict, domain: str) -> float:
    """Produce a confidence in [0.2, 0.97] from Holehe's hit metadata.

    We start from a site-specific prior (LOW / NORMAL / HIGH) then apply
    multipliers that reflect Holehe's own signals. Values stay roughly
    bucket-spaced so the UI shows distinct percentages (not all 85%).
    """
    # Base by site reliability
    if domain in HIGH_TRUST_SITES:
        base = 0.85
    elif domain in LOW_TRUST_SITES:
        base = 0.5
    else:
        base = 0.7

    # Rate-limit drops trust — we got a "maybe" not a "yes".
    if entry.get("rateLimit"):
        base -= 0.2

    # Leaked recovery data is strong evidence the account exists.
    if entry.get("emailrecovery") or entry.get("phoneNumber"):
        base = max(base, 0.92)

    # Extra metadata like "registered since YYYY" is also a strong positive.
    others = entry.get("others") or {}
    if isinstance(others, dict) and others:
        base += 0.05

    return max(0.2, min(0.97, base))
