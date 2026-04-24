"""Maigret connector — username profile discovery across ~2500 sites.

We only emit ACCOUNT findings now (previously we also emitted a redundant
URL finding for every hit). The `value` of an ACCOUNT is the full profile
URL so it's immediately useful: the UI renders it as a clickable link,
the profile_scraper can accept it as input, and the user sees a single
node per platform instead of two.

Input : DataType.USERNAME
Output: DataType.ACCOUNT (one per matched site)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)


@register
class MaigretConnector(BaseConnector):
    name = "maigret"
    display_name = "Maigret — username profile discovery"
    category = ConnectorCategory.USERNAME
    description = (
        "Scans ~2500 public sites to find where a username has registered a "
        "profile. No authentication, no notifications. Each match produces "
        "one ACCOUNT finding whose value is the full profile URL."
    )
    homepage_url = "https://github.com/soxoj/maigret"
    input_types = {DataType.USERNAME}
    output_types = {DataType.ACCOUNT}
    timeout_seconds = 180

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.USERNAME:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        username = input_value.strip()
        if not username or " " in username:
            return ConnectorResult(error="Username must be non-empty and whitespace-free")

        try:
            import maigret as maigret_pkg
            from maigret.sites import MaigretDatabase
            from maigret.maigret import maigret as maigret_run
        except ImportError as exc:
            return ConnectorResult(error=f"Maigret library not available: {exc}")

        try:
            db_path = os.path.join(maigret_pkg.__path__[0], "resources", "data.json")
            db = MaigretDatabase().load_from_file(db_path)
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Failed to load Maigret site DB: {exc}")

        try:
            results: dict[str, Any] = await maigret_run(
                username=username,
                site_dict=db.sites_dict,
                logger=logger,
                timeout=15,
                id_type="username",
                max_connections=50,
                forced=False,
                no_progressbar=True,
                cookies=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Maigret search failed")
            return ConnectorResult(error=f"Maigret search failed: {type(exc).__name__}: {exc}")

        findings: list[Finding] = []
        seen_urls: set[str] = set()

        for site_name, info in (results or {}).items():
            if not isinstance(info, dict):
                continue
            status = info.get("status")
            try:
                if not (status and status.is_found()):
                    continue
            except Exception:  # noqa: BLE001
                continue

            url = info.get("url_user") or info.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Maigret already validated via its own HTTP check — the url is
            # reachable and content-matches. We use a high confidence prior.
            findings.append(
                Finding(
                    data_type=DataType.ACCOUNT,
                    value=url,                 # ← full URL, human-readable
                    confidence=0.88,
                    source_url=url,
                    extracted_at=now_utc(),
                    raw={"site": site_name, "url": url},
                    notes=f"Profil trouvé sur {site_name}",
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={
                "sites_scanned": len(results or {}),
                "matches": len(findings),
            },
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            import maigret  # noqa: F401
            return HealthStatus.OK
        except ImportError:
            return HealthStatus.DEAD
