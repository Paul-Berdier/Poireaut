"""Unit tests for password hashing + JWT issuance / verification."""
import uuid

import pytest

from src.services.auth import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hashing_roundtrip() -> None:
    hashed = hash_password("s3cret-passw0rd")
    assert hashed != "s3cret-passw0rd"
    assert verify_password("s3cret-passw0rd", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_jwt_roundtrip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id)
    assert expires_in > 0

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"


def test_jwt_rejects_garbage() -> None:
    with pytest.raises(TokenError):
        decode_access_token("not.a.token")
