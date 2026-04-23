"""Authentication routes.

/auth/register can be disabled in production via ALLOW_REGISTRATION=false —
in which case only a manually-seeded admin user can log in.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config import get_settings
from src.deps import CurrentUser, DbSession
from src.models.user import User
from src.schemas.auth import RegisterIn, TokenOut, UserOut
from src.services.auth import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(payload: RegisterIn, db: DbSession) -> User:
    settings = get_settings()
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )

    user = User(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
async def login(
    # OAuth2PasswordRequestForm reads `username` and `password` from form data,
    # matching the FastAPI Swagger "Authorize" button out of the box.
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenOut:
    stmt = select(User).where(User.email == form.username.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    token, expires_in = create_access_token(user.id)
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
