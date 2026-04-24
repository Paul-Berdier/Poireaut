"""Wayback Machine connector.

The Internet Archive's Wayback Machine keeps snapshots of URLs over time.
Given a URL, we can ask for the first, last and sample intermediate
captures — useful when a page was edited or deleted and you need to know
what it used to say.

Uses the CDX API (https://archive.org/wayback/available and cdx.web.archive.org).
Input : DataType.URL
Output: a small set of DataType.URL findings, each pointing to a snapshot
        with the capture date in the notes.

Fully free, no auth. Generous rate limits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.connectors.base import BaseConnector, ConnectorResult, Finding, now_utc
from src.connectors.registry import register
from src.db.types import ConnectorCategory, DataType, HealthStatus

logger = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"


@register
class WaybackConnector(BaseConnector):
    name = "wayback"
    display_name = "Wayback Machine — historical URL snapshots"
    category = ConnectorCategory.ARCHIVE
    description = (
        "Queries the Internet Archive's Wayback Machine for historical "
        "captures of the submitted URL. Returns the first, last and sampled "
        "intermediate snapshots so you can compare what the page said over "
        "time or recover deleted content."
    )
    homepage_url = "https://web.archive.org"
    input_types = {DataType.URL}
    output_types = {DataType.URL}
    timeout_seconds = 30

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.URL:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")

        target = input_value.strip()
        if not target.startswith(("http://", "https://")):
            return ConnectorResult(error="URL must start with http:// or https://")

        params = {
            "url": target,
            "output": "json",
            "fl": "timestamp,original,statuscode,mimetype",
            "filter": "statuscode:200",
            "collapse": "timestamp:6",  # collapse by year-month → ~12/year max
            "limit": "50",
        }
        try:
            async with httpx.AsyncClient(
                timeout=20,
                headers={"user-agent": "poireaut/0.5 (+osint-research)"},
            ) as client:
                resp = await client.get(CDX_URL, params=params)
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Wayback HTTP error: {exc}")

        if resp.status_code != 200:
            return ConnectorResult(error=f"Wayback returned {resp.status_code}")

        try:
            rows: list[list[str]] = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"Wayback response not JSON: {exc}")

        # First row is the header. Skip it.
        if not rows or rows[0][:2] != ["timestamp", "original"]:
            return ConnectorResult(findings=[], raw_output={"snapshots": 0})
        data = rows[1:]
        if not data:
            return ConnectorResult(findings=[], raw_output={"snapshots": 0})

        # Sample: first, last, and up to 3 in the middle spread evenly.
        picks = _pick_samples(data, max_samples=5)

        findings: list[Finding] = []
        for row in picks:
            ts, original, _status, _mime = row[0], row[1], row[2], row[3]
            snapshot_url = f"https://web.archive.org/web/{ts}/{original}"
            captured = _parse_ts(ts)
            findings.append(
                Finding(
                    data_type=DataType.URL,
                    value=snapshot_url,
                    confidence=0.95,
                    source_url=snapshot_url,
                    extracted_at=captured,
                    notes=f"Captured {captured:%Y-%m-%d}" if captured else None,
                )
            )

        return ConnectorResult(
            findings=findings,
            raw_output={"snapshots": len(data), "sampled": len(findings)},
        )

    async def healthcheck(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://archive.org/wayback/available",
                    params={"url": "example.com"},
                )
                return HealthStatus.OK if r.status_code == 200 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD


def _pick_samples(rows: list[list[str]], *, max_samples: int) -> list[list[str]]:
    if len(rows) <= max_samples:
        return list(rows)
    n = len(rows)
    # first, last, and (max_samples - 2) spread in between
    picks = [rows[0], rows[-1]]
    middle = max_samples - 2
    if middle > 0:
        for i in range(1, middle + 1):
            idx = round(i * (n - 1) / (middle + 1))
            picks.insert(-1, rows[idx])
    # de-dup in case of rounding collisions
    seen = set()
    unique = []
    for r in picks:
        key = r[0]
        if key in seen: continue
        seen.add(key); unique.append(r)
    return unique


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
