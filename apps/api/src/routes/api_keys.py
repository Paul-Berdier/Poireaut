"""API key management routes (per-user).

GET    /me/api-keys            list current user's keys (masked)
PUT    /me/api-keys/{name}     set or replace a key
DELETE /me/api-keys/{name}     remove a key
POST   /me/api-keys/{name}/test   run the connector's healthcheck with this key

All operations are user-scoped. The plaintext key value is never returned —
only the masked preview is shown back. To rotate, the user re-PUTs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.deps import CurrentUser, DbSession
from src.services.api_keys import (
    delete_key,
    get_key_record,
    list_keys_for_user,
    upsert_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/me/api-keys", tags=["api-keys"])


# ─── Schemas ──────────────────────────────────────────

class ApiKeyOut(BaseModel):
    connector_name: str
    masked_preview: str
    created_at: datetime
    last_used_at: datetime | None
    last_test_at: datetime | None
    last_test_ok: bool | None


class ApiKeyPut(BaseModel):
    value: str = Field(min_length=4, max_length=1024,
                       description="Plaintext API key. Stored encrypted.")


class ApiKeyTestResult(BaseModel):
    connector_name: str
    ok: bool
    detail: str


# ─── Helpers ──────────────────────────────────────────

# Whitelist of connectors that take API keys. We refuse PUTs for any other
# name so a typo doesn't silently land in the DB as a useless row.
_KEY_CONNECTORS = {
    "ipinfo", "numverify", "hunter", "shodan", "facecheck",
    "openai", "hibp",
}


def _ensure_known(connector_name: str) -> None:
    if connector_name not in _KEY_CONNECTORS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Connecteur inconnu '{connector_name}'. "
                f"Connecteurs attendant une clé : {', '.join(sorted(_KEY_CONNECTORS))}"
            ),
        )


# ─── Routes ───────────────────────────────────────────

@router.get("", response_model=list[ApiKeyOut])
async def list_my_keys(user: CurrentUser, db: DbSession) -> list[ApiKeyOut]:
    rows = await list_keys_for_user(db, user.id)
    return [
        ApiKeyOut(
            connector_name=r.connector_name,
            masked_preview=r.masked_preview,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            last_test_at=r.last_test_at,
            last_test_ok=r.last_test_ok,
        )
        for r in rows
    ]


@router.put("/{connector_name}", response_model=ApiKeyOut)
async def set_my_key(
    connector_name: str,
    payload: ApiKeyPut,
    user: CurrentUser,
    db: DbSession,
) -> ApiKeyOut:
    _ensure_known(connector_name)
    row = await upsert_key(db, user.id, connector_name, payload.value.strip())
    return ApiKeyOut(
        connector_name=row.connector_name,
        masked_preview=row.masked_preview,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
    )


@router.delete(
    "/{connector_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_my_key(
    connector_name: str,
    user: CurrentUser,
    db: DbSession,
) -> None:
    _ensure_known(connector_name)
    removed = await delete_key(db, user.id, connector_name)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune clé configurée pour ce connecteur",
        )


@router.post("/{connector_name}/test", response_model=ApiKeyTestResult)
async def test_my_key(
    connector_name: str,
    user: CurrentUser,
    db: DbSession,
) -> ApiKeyTestResult:
    """Probe the provider's API with the stored key and report ok/not-ok.

    Each connector has a tiny "is the key valid" check defined inline
    here. We don't import worker modules from the API container (different
    image, different requirements) — we do a minimal HTTP probe per service.
    """
    _ensure_known(connector_name)
    row = await get_key_record(db, user.id, connector_name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune clé configurée — utilisez PUT pour en ajouter une",
        )

    from src.services.api_keys import decrypt_value

    try:
        plaintext = decrypt_value(row.encrypted_value)
    except ValueError as exc:
        return ApiKeyTestResult(
            connector_name=connector_name, ok=False,
            detail=f"Impossible de déchiffrer la clé : {exc}",
        )

    ok, detail = await _probe_provider(connector_name, plaintext)

    row.last_test_at = datetime.now(timezone.utc)
    row.last_test_ok = ok
    # get_db() commits at end of request — no explicit commit needed.

    return ApiKeyTestResult(connector_name=connector_name, ok=ok, detail=detail)


async def _probe_provider(name: str, key: str) -> tuple[bool, str]:
    """Lightweight HTTP probe per provider. Returns (ok, human reason)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            if name == "ipinfo":
                r = await c.get("https://ipinfo.io/8.8.8.8/json", params={"token": key})
                return r.status_code == 200, f"HTTP {r.status_code}"
            if name == "numverify":
                r = await c.get("http://apilayer.net/api/validate", params={
                    "access_key": key, "number": "14158586273",
                })
                if r.status_code != 200:
                    return False, f"HTTP {r.status_code}"
                body = r.json()
                if body.get("success") is False:
                    return False, f"API: {body.get('error', {}).get('info', 'invalid')}"
                return True, "OK"
            if name == "hunter":
                r = await c.get("https://api.hunter.io/v2/account", params={"api_key": key})
                return r.status_code == 200, f"HTTP {r.status_code}"
            if name == "shodan":
                r = await c.get("https://api.shodan.io/api-info", params={"key": key})
                return r.status_code == 200, f"HTTP {r.status_code}"
            if name == "facecheck":
                r = await c.get("https://facecheck.id/api/credits",
                                headers={"Authorization": key})
                return r.status_code in (200, 201), f"HTTP {r.status_code}"
            if name == "openai":
                r = await c.get("https://api.openai.com/v1/models",
                                headers={"Authorization": f"Bearer {key}"})
                return r.status_code == 200, f"HTTP {r.status_code}"
            if name == "hibp":
                r = await c.get(
                    "https://haveibeenpwned.com/api/v3/breachedaccount/test@example.com",
                    headers={"hibp-api-key": key, "user-agent": "poireaut-test"},
                )
                # HIBP: 200 = found, 404 = not found (both = key OK), 401 = bad key
                return r.status_code in (200, 404), f"HTTP {r.status_code}"
            return False, f"No probe defined for {name}"
    except httpx.HTTPError as exc:
        return False, f"HTTP error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
