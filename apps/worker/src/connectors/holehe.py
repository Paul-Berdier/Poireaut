"""Holehe connector.

Holehe (https://github.com/megadose/holehe) uses forgotten-password flows to
detect whether an email is registered on ~120 platforms (Instagram, Twitter,
Spotify, …). It does not log in and does not trigger password reset emails
for the target — it only probes public signup endpoints.

Input : DataType.EMAIL
Output: one DataType.ACCOUNT finding per platform where the email was found.

The `holehe` Python library doesn't expose a proper public API — it's built
as a CLI. We call its internal async modules directly. Each module is one
file like `holehe.modules.social_media.twitter`. We iterate over all modules,
feed them the email, and collect the ones that say `exists: True`.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType

logger = logging.getLogger(__name__)


@register
class HoleheConnector(BaseConnector):
    name = "holehe"
    display_name = "Holehe — email account discovery"
    category = ConnectorCategory.EMAIL
    description = (
        "Probes ~120 popular sites to see whether the supplied email address "
        "has an account there. Uses each site's public forgot-password or "
        "signup endpoint. No login is attempted and no notification is sent "
        "to the target."
    )
    homepage_url = "https://github.com/megadose/holehe"
    input_types = {DataType.EMAIL}
    output_types = {DataType.ACCOUNT}
    timeout_seconds = 45

    def _discover_modules(self) -> list:
        """Enumerate all holehe modules at runtime.

        Holehe organises its checks under `holehe.modules.*`. Each module
        exposes a single async function named after the module (e.g.
        `holehe.modules.social_media.twitter.twitter`). We reflect them
        to avoid a hardcoded list that would go stale with every holehe
        release.
        """
        try:
            from holehe import modules as holehe_modules
        except ImportError:
            return []

        funcs = []
        for _finder, mod_name, _is_pkg in pkgutil.walk_packages(
            holehe_modules.__path__, prefix="holehe.modules."
        ):
            if _is_pkg:
                continue
            try:
                module = importlib.import_module(mod_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping holehe module %s: %s", mod_name, exc)
                continue
            # The callable is usually named after the last path segment.
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
            return ConnectorResult(
                error="Holehe library not installed or exposes no modules"
            )

        findings: list[Finding] = []
        errors: list[str] = []

        # One shared httpx client so connections are pooled across modules.
        async with httpx.AsyncClient(
            timeout=8.0,
            headers={"User-Agent": "poireaut/0.3 (+osint)"},
        ) as client:
            for site_name, fn in modules:
                out: list[dict[str, Any]] = []
                try:
                    # Every holehe module has the signature:
                    #     async def foo(email, client, out)
                    # where `out` is the list it appends results to.
                    await fn(email, client, out)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{site_name}: {type(exc).__name__}")
                    continue

                for entry in out:
                    if not entry.get("exists"):
                        continue
                    domain = entry.get("domain") or site_name
                    rate_limited = bool(entry.get("rateLimit"))
                    findings.append(
                        Finding(
                            data_type=DataType.ACCOUNT,
                            value=domain,
                            confidence=0.85 if not rate_limited else 0.55,
                            source_url=_homepage_for(domain),
                            extracted_at=now_utc(),
                            raw=entry,
                            notes=(
                                f"Account likely exists on {domain}"
                                + (" (site rate-limited — lower confidence)" if rate_limited else "")
                            ),
                        )
                    )

        raw = {"modules_total": len(modules), "errors": errors[:20]}
        return ConnectorResult(findings=findings, raw_output=raw)

    def _healthcheck_probe(self) -> tuple[str, DataType] | None:
        # Probing Holehe would hit ~120 sites. Skip the default probe and
        # assert health by presence of the library instead.
        return None

    async def healthcheck(self):
        from src.db.types import HealthStatus

        try:
            import holehe.modules  # noqa: F401
            return HealthStatus.OK
        except ImportError:
            return HealthStatus.DEAD


def _homepage_for(domain: str) -> str | None:
    """Best-effort URL for the UI to link to."""
    if not domain:
        return None
    if domain.startswith("http"):
        return domain
    return f"https://{domain.lstrip('.')}"
