"""OpenAI-powered synthesis of an investigation.

Endpoint: POST /investigations/{id}/synthesize

Pulls the investigation's validated datapoints, formats them as a compact
JSON brief, sends it to OpenAI's chat completions API with a "be concise,
French, list the strong hypotheses" prompt, and streams the result back.

This is intentionally simple — no fine-tuning, no embeddings, no RAG.
Just "here are 30 facts, summarize what they suggest about the target".

Requires OPENAI_API_KEY in the API service env. Without it, returns 503.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from src.db.types import VerificationStatus
from src.deps import CurrentUser, DbSession
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation

logger = logging.getLogger(__name__)
router = APIRouter(tags=["synthesis"])

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class SynthesisRequest(BaseModel):
    only_validated: bool = True
    max_datapoints: int = 80


class SynthesisResponse(BaseModel):
    summary: str
    datapoints_used: int
    model: str


@router.post(
    "/investigations/{investigation_id}/synthesize",
    response_model=SynthesisResponse,
)
async def synthesize_investigation(
    investigation_id: uuid.UUID,
    payload: SynthesisRequest,
    user: CurrentUser,
    db: DbSession,
) -> SynthesisResponse:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI key not configured on the server",
        )

    inv = await db.get(Investigation, investigation_id)
    if inv is None or inv.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Load the investigation's datapoints (only validated by default)
    stmt = (
        select(DataPoint)
        .join(Entity, DataPoint.entity_id == Entity.id)
        .where(Entity.investigation_id == investigation_id)
    )
    if payload.only_validated:
        stmt = stmt.where(DataPoint.status == VerificationStatus.VALIDATED)
    stmt = stmt.order_by(DataPoint.created_at).limit(payload.max_datapoints)
    dps = list((await db.execute(stmt)).scalars().all())
    if not dps:
        return SynthesisResponse(
            summary="Aucune donnée à synthétiser pour le moment.",
            datapoints_used=0,
            model=OPENAI_MODEL,
        )

    # Compact JSON representation — keep the prompt tight.
    brief = [
        {
            "type": dp.type.value,
            "value": dp.value[:200],
            "status": dp.status.value,
            "confidence": dp.confidence,
            "source": dp.source_url,
            "notes": (dp.notes or "")[:200],
        }
        for dp in dps
    ]

    system_prompt = (
        "Tu es un assistant d'enquête OSINT. Réponds en français concis. "
        "À partir de la liste de datapoints fournie, produis un rapport "
        "structuré en 4 sections :\n"
        "1. Profil probable de la cible (nom, âge approximatif, localisation, profession)\n"
        "2. Présence en ligne (plateformes, comptes les plus actifs)\n"
        "3. Hypothèses non vérifiées (avec le niveau de confiance)\n"
        "4. Pistes à approfondir (suggestions concrètes pour la prochaine enquête)\n\n"
        "Sois sobre, n'invente rien. Quand un fait est incertain, dis-le."
    )
    user_prompt = (
        f"Enquête: {inv.title}\n\n"
        f"Datapoints ({len(brief)} sur {len(dps)} chargés) :\n"
        f"{brief}"
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1200,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI request failed: {exc}",
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI returned {resp.status_code}: {resp.text[:300]}",
        )

    try:
        data: dict[str, Any] = resp.json()
        summary = data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI response malformed: {exc}",
        )

    return SynthesisResponse(
        summary=summary.strip(),
        datapoints_used=len(dps),
        model=OPENAI_MODEL,
    )
