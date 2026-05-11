"""FaceCheck.id connector.

FaceCheck does real reverse face search: you upload a face image, they
return URLs of pages where they found the same face online. Much more
focused than generic reverse-image which finds the same image, not the
same person.

Pricing as of 2026: $19/mo for 50 credits/day, $499/mo for 500/day.
Each search costs 1 credit. Without a key, the connector is disabled.

The free `reverse_image` connector still works alongside this one and
costs nothing — they complement each other (FaceCheck for faces, the
3 search engines for everything else).

Input : DataType.PHOTO
Output: URL (one per matching profile/page found)
"""
from __future__ import annotations

import asyncio
import base64
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

FACECHECK_BASE = "https://facecheck.id/api"


@register
class FaceCheckConnector(BaseConnector):
    name = "facecheck"
    display_name = "FaceCheck.id — recherche faciale inverse"
    category = ConnectorCategory.IMAGE
    description = (
        "Reconnaissance faciale inversée : trouve les pages web où un "
        "visage donné apparaît. Plus précis que la recherche d'image "
        "classique (cible la personne, pas l'image). Payant (≈19€/mo)."
    )
    homepage_url = "https://facecheck.id"
    input_types = {DataType.PHOTO}
    output_types = {DataType.URL}
    cost = ConnectorCost.PAID
    timeout_seconds = 120  # face search jobs can take 30-90s

    @property
    def _api_token(self) -> str | None:
        return os.getenv("FACECHECK_API_TOKEN") or None

    async def run(self, input_value: str, input_type: DataType) -> ConnectorResult:
        if input_type is not DataType.PHOTO:
            return ConnectorResult(error=f"Unsupported input type: {input_type}")
        token = self._api_token
        if not token:
            return ConnectorResult(error="FACECHECK_API_TOKEN not set — skipping")

        image_url = input_value.strip()
        if not image_url.startswith(("http://", "https://")):
            return ConnectorResult(error="Photo value must be a URL")

        # FaceCheck wants the image file, not a URL. Fetch it first.
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                img_resp = await client.get(image_url, headers={
                    "user-agent": "Mozilla/5.0 (poireaut)",
                })
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"Could not fetch image: {exc}")
        if img_resp.status_code >= 400:
            return ConnectorResult(error=f"Image fetch returned {img_resp.status_code}")
        img_bytes = img_resp.content

        headers = {"Authorization": token, "accept": "application/json"}

        # 1. Upload + start the search
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                files = {"images": ("face.jpg", img_bytes)}
                up = await client.post(
                    f"{FACECHECK_BASE}/upload_pic",
                    headers=headers,
                    files=files,
                )
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"FaceCheck upload failed: {exc}")
        if up.status_code != 200:
            return ConnectorResult(error=f"FaceCheck upload returned {up.status_code}")
        try:
            up_body = up.json()
        except Exception as exc:  # noqa: BLE001
            return ConnectorResult(error=f"FaceCheck upload JSON: {exc}")
        if up_body.get("error"):
            return ConnectorResult(error=f"FaceCheck error: {up_body['error']}")

        id_search = up_body.get("id_search")
        if not id_search:
            return ConnectorResult(error="FaceCheck: missing id_search in response")

        # 2. Poll for results (FaceCheck does background processing)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                for _ in range(20):
                    sr = await client.post(
                        f"{FACECHECK_BASE}/search",
                        headers=headers,
                        json={"id_search": id_search, "with_progress": True, "demo": False},
                    )
                    if sr.status_code != 200:
                        return ConnectorResult(error=f"FaceCheck search returned {sr.status_code}")
                    body = sr.json()
                    code = body.get("code")
                    if code == 200:
                        break
                    if code and code >= 400:
                        return ConnectorResult(error=f"FaceCheck: {body.get('message', 'error')}")
                    await asyncio.sleep(3)
                else:
                    return ConnectorResult(error="FaceCheck timed out waiting for results")
        except httpx.HTTPError as exc:
            return ConnectorResult(error=f"FaceCheck polling failed: {exc}")

        results = body.get("output", {}).get("items") or []
        findings: list[Finding] = []
        for item in results[:50]:  # cap to top 50
            url = item.get("url")
            score = item.get("score", 0)
            if not url:
                continue
            # FaceCheck score: 0-100
            cb = build("facecheck.match", 0.65, "Correspondance faciale FaceCheck")
            if isinstance(score, (int, float)):
                cb.add(
                    "facecheck.score_bonus",
                    min(0.3, score / 200),
                    f"Score FaceCheck {score}/100",
                )
            findings.append(Finding(
                data_type=DataType.URL,
                value=url,
                confidence=round(cb.compose(), 2),
                source_url=url,
                extracted_at=now_utc(),
                raw={"facecheck_score": score, "_signals": cb.to_raw()},
                notes=f"Visage similaire trouvé (score FaceCheck {score})",
            ))

        return ConnectorResult(
            findings=findings,
            raw_output={"id_search": id_search, "matches": len(results)},
        )

    async def healthcheck(self) -> HealthStatus:
        if not self._api_token:
            return HealthStatus.DEGRADED
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                # No public ping endpoint; check the API base responds.
                r = await c.get("https://facecheck.id")
                return HealthStatus.OK if r.status_code < 500 else HealthStatus.DEGRADED
        except Exception:  # noqa: BLE001
            return HealthStatus.DEAD
