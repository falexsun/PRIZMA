from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.jwt import TokenError, create_access_token, create_refresh_token, decode_token
from app.core.rate_limit import rate_limit
from app.core.security import verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenPair,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenPair)
@rate_limit(times=5, seconds=60)  # 5 attempts per minute per IP
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    user = (await db.execute(select(User).where(User.login == payload.login))).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login or password")

    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.role.value),
    )


@router.post("/auth/refresh", response_model=AccessTokenResponse)
@rate_limit(times=10, seconds=60)  # 10 refreshes per minute per IP
async def refresh(request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

    user_id = int(token_payload["sub"])
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    return AccessTokenResponse(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
