"""Maigret connector.

Maigret (https://github.com/soxoj/maigret) is Holehe's bigger sibling for
usernames: it checks ~2500 sites for a given pseudo and returns the URL of
every profile found. Where Holehe probes email registration endpoints,
Maigret scrapes public profile pages and validates existence by HTTP status
+ page contents.

Input : DataType.USERNAME
Output: one DataType.ACCOUNT finding per site where the profile exists,
        plus surfaced DataType.URL for the profile permalinks.

Maigret is slow — a full scan against 2500 sites can take minutes. We use
its default database but cap the per-site timeout so a slow/flaky scan
doesn't block the Celery worker forever. Total run is bounded by
`timeout_seconds` in BaseConnector (enforced by the orchestrator).
"""
from __future__ import annotations

import logging
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
        "Scans ~2500 public sites to find where a username has registered "
        "a profile. No authentication, no notifications sent to the target. "
        "Returns the profile URLs it validates."
    )
    homepage_url = "https://github.com/soxoj/maigret"
    input_types = {DataType.USERNAME}
    output_types = {DataType.ACCOUNT, DataType.URL}
    timeout_seconds = 180  # Maigret is slow — give it 3 minutes

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.USERNAME:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        username = input_value.strip()
        if not username or " " in username:
            return ConnectorResult(error="Username must be non-empty and whitespace-free")

        # Lazy import: maigret is heavy, keep it out of module-load time.
        try:
            import maigret as maigret_pkg
            from maigret.sites import MaigretDatabase
            from maigret.maigret import maigret as maigret_run
        except ImportError as exc:
            return ConnectorResult(error=f"Maigret library not available: {exc}")

        # Load the bundled site database.
        try:
            import os
            db_path = os.path.join(maigret_pkg.__path__[0], "resources", "data.json")
            db = MaigretDatabase().load_from_file(db_path)
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Failed to load Maigret site DB: {exc}")

        try:
            # Signature:
            #   maigret(username, site_dict, logger, *, timeout=3,
            #           id_type="username", max_connections=100, forced=False,
            #           no_progressbar=False, cookies=None, ...)
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
        for site_name, info in (results or {}).items():
            # `info` is a QueryResultWrapper. Access the inner status.
            status = info.get("status") if isinstance(info, dict) else None
            found = False
            try:
                found = bool(status and status.is_found())
            except Exception:  # noqa: BLE001
                found = False
            if not found:
                continue

            url = (info.get("url_user") if isinstance(info, dict) else None) \
                  or (info.get("url") if isinstance(info, dict) else None)
            if not url:
                continue

            findings.append(
                Finding(
                    data_type=DataType.ACCOUNT,
                    value=site_name,
                    confidence=0.9,
                    source_url=url,
                    extracted_at=now_utc(),
                    raw={"site": site_name, "url": url},
                    notes=f"Profile found on {site_name}",
                )
            )
            findings.append(
                Finding(
                    data_type=DataType.URL,
                    value=url,
                    confidence=0.9,
                    source_url=url,
                    extracted_at=now_utc(),
                    notes=f"Profile URL on {site_name}",
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={
                "sites_scanned": len(results or {}),
                "matches": len(findings) // 2,
            },
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            import maigret  # noqa: F401
            return HealthStatus.OK
        except ImportError:
            return HealthStatus.DEAD
