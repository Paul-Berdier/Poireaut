"""Health-check route. Railway hits /health on each deploy."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    service: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        service="poireaut-api",
    )
