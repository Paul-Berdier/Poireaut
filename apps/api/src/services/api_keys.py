"""Encryption + DB accessors for API keys.

Single source of truth for how API keys are stored/retrieved/encrypted.
Both the API (CRUD) and the worker (key retrieval at runtime) use these.
"""
from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.api_key import ApiKey

logger = logging.getLogger(__name__)

_FERNET: Fernet | None = None
_FERNET_ENV_VAR = "POIREAUT_FERNET_KEY"


def _get_fernet() -> Fernet:
    """Cache the Fernet instance — re-read env on first call."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    raw = os.getenv(_FERNET_ENV_VAR)
    if not raw:
        # Auto-derive a stable key from JWT_SECRET as a fallback. This lets
        # the app work out of the box (no manual key generation) while
        # still being a real symmetric key. Users with strict security
        # requirements should set POIREAUT_FERNET_KEY explicitly.
        seed = os.getenv("JWT_SECRET", "poireaut-default-fernet-seed-change-me")
        # Fernet expects a 32-byte url-safe base64 string. Derive deterministically.
        import hashlib
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        raw = base64.urlsafe_b64encode(digest).decode("ascii")
        logger.warning(
            "POIREAUT_FERNET_KEY not set — derived from JWT_SECRET. "
            "Set it explicitly for production."
        )
    try:
        _FERNET = Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
    except Exception as exc:
        raise RuntimeError(
            f"Invalid POIREAUT_FERNET_KEY: {exc}. "
            "Must be a 32-byte url-safe base64 string."
        ) from exc
    return _FERNET


def encrypt_value(plaintext: str) -> str:
    """Encrypt a key value. Returns a url-safe base64 string."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(token: str) -> str:
    """Decrypt; raises on failure."""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt: wrong Fernet key or corrupted value") from exc


def mask(plaintext: str) -> str:
    """Render a safe preview, like 'sk-•••a1b2'.

    Keeps a short prefix when present (e.g. 'sk-', 'AIza', 'eyJ') and
    the last 4 characters. Hides everything in between.
    """
    if not plaintext:
        return "•••"
    head = ""
    rest = plaintext
    if "-" in plaintext[:10]:
        head, _, rest = plaintext.partition("-")
        head += "-"
    if len(rest) <= 8:
        return f"{head}•••{rest[-2:]}"
    return f"{head}•••{rest[-4:]}"


# ─── DB accessors ─────────────────────────────────────

async def list_keys_for_user(
    db: AsyncSession, user_id: uuid.UUID,
) -> list[ApiKey]:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.connector_name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_key_record(
    db: AsyncSession, user_id: uuid.UUID, connector_name: str,
) -> ApiKey | None:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.connector_name == connector_name)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_key(
    db: AsyncSession, user_id: uuid.UUID, connector_name: str, plaintext: str,
) -> ApiKey:
    """Insert or replace a key for (user, connector). Returns the row."""
    existing = await get_key_record(db, user_id, connector_name)
    encrypted = encrypt_value(plaintext)
    masked = mask(plaintext)
    if existing is None:
        row = ApiKey(
            user_id=user_id,
            connector_name=connector_name,
            encrypted_value=encrypted,
            masked_preview=masked,
        )
        db.add(row)
        await db.flush()
        return row
    existing.encrypted_value = encrypted
    existing.masked_preview = masked
    existing.last_test_at = None
    existing.last_test_ok = None
    await db.flush()
    return existing


async def delete_key(
    db: AsyncSession, user_id: uuid.UUID, connector_name: str,
) -> bool:
    """Delete a key. Returns True if a row was deleted."""
    row = await get_key_record(db, user_id, connector_name)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def get_api_key_plaintext(
    db: AsyncSession, user_id: uuid.UUID, connector_name: str,
) -> str | None:
    """Used by the worker to fetch a decrypted key at runtime.

    Falls back to env var <CONNECTOR>_API_KEY style names so legacy
    deployments keep working: e.g. HUNTER_API_KEY → connector "hunter".
    """
    row = await get_key_record(db, user_id, connector_name)
    if row is not None:
        # Stamp usage time for the UI's "last used" column
        row.last_used_at = datetime.now(timezone.utc)
        try:
            return decrypt_value(row.encrypted_value)
        except ValueError:
            logger.exception(
                "Cannot decrypt key for user=%s connector=%s — fernet key changed?",
                user_id, connector_name,
            )
            return None

    # Env-var fallback for backwards compat
    env_name = f"{connector_name.upper()}_API_KEY"
    env_value = os.getenv(env_name)
    if env_value:
        return env_value
    # Also try _TOKEN suffix (FaceCheck uses FACECHECK_API_TOKEN)
    return os.getenv(f"{connector_name.upper()}_API_TOKEN")
