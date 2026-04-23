"""Password hashing and JWT token issuance / verification."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import get_settings

settings = get_settings()

# bcrypt via passlib. `bcrypt==4.0.1` is pinned in requirements; passlib's
# bcrypt backend breaks on bcrypt >= 4.1 (it calls __about__.__version__
# which was removed).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Passwords ──────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ─── JWT ────────────────────────────────────────────────────

def create_access_token(user_id: uuid.UUID, *, extra: dict[str, Any] | None = None) -> tuple[str, int]:
    """Return (encoded_token, expires_in_seconds)."""
    expires_in = settings.jwt_access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


class TokenError(Exception):
    """Raised when a JWT is invalid, expired or malformed."""


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("wrong token type")
    if "sub" not in payload:
        raise TokenError("missing subject")
    return payload
