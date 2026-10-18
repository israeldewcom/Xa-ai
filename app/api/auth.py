import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.exceptions import AuthenticationError, ConflictError, NotFound
from app.core.rate_limit import RateLimiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.database.models import ApiKey, RefreshToken, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.auth import (
    ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, LoginRequest,
    RefreshRequest, RegisterRequest, TokenResponse, UserResponse,
)

logger = logging.getLogger("xa.api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    request: Request, payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    limiter: RateLimiter = request.app.state.login_limiter
    await limiter.check(f"register:{request.client.host if request.client else 'na'}")

    existing = (await db.execute(
        select(User).where(User.email == payload.email)
    )).scalar_one_or_none()
    if existing:
        raise ConflictError("Email already registered.")

    user = User(
        email=payload.email, password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit_record(
        db, actor_id=user.id, action="auth.register",
        resource_type="user", resource_id=user.id,
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request, payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    limiter: RateLimiter = request.app.state.login_limiter
    key = f"login:{payload.email}:{request.client.host if request.client else 'na'}"
    await limiter.check(key)

    user = (await db.execute(
        select(User).where(User.email == payload.email)
    )).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid credentials.")
    if user.status != "active":
        raise AuthenticationError("Account inactive.")

    access = create_access_token(user.id, user.role)
    refresh, jti, expires = create_refresh_token(user.id)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires))
    await db.commit()
    return TokenResponse(
        access_token=access, refresh_token=refresh,
        expires_in=30 * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest, db: AsyncSession = Depends(get_db),
):
    try:
        data = decode_token(payload.refresh_token)
    except Exception:
        raise AuthenticationError("Invalid refresh token.")
    if data.get("type") != "refresh":
        raise AuthenticationError("Not a refresh token.")
    jti = data.get("jti")
    rec = await db.get(RefreshToken, jti)
    if rec is None or rec.revoked:
        raise AuthenticationError("Refresh token revoked.")
    if rec.expires_at < datetime.now(timezone.utc):
        raise AuthenticationError("Refresh token expired.")
    user = await db.get(User, data["sub"])
    if user is None or user.status != "active":
        raise AuthenticationError("User inactive.")
    rec.revoked = True
    access = create_access_token(user.id, user.role)
    new_refresh, new_jti, new_expires = create_refresh_token(user.id)
    db.add(RefreshToken(jti=new_jti, user_id=user.id, expires_at=new_expires))
    await db.commit()
    return TokenResponse(
        access_token=access, refresh_token=new_refresh, expires_in=30 * 60,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    payload: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw, prefix, h = generate_api_key()
    record = ApiKey(
        user_id=user.id, name=payload.name, prefix=prefix, key_hash=h,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return ApiKeyCreatedResponse(
        id=record.id, name=record.name, prefix=record.prefix,
        created_at=record.created_at, last_used_at=record.last_used_at,
        expires_at=record.expires_at, secret=raw,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id)
    )).scalars().all()
    return [ApiKeyResponse.model_validate(r) for r in rows]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await db.get(ApiKey, key_id)
    if rec is None or rec.user_id != user.id:
        raise NotFound("API key not found.")
    rec.revoked = True
    await db.commit()
