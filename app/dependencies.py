from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError
from app.core.security import decode_token, hash_api_key, require_bearer
from app.database.models import ApiKey, User
from app.database.session import get_db
from app.orchestration.registry import ModelRegistry
from app.orchestration.router import RequestRouter


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id: str | None = None
    if x_api_key:
        h = hash_api_key(x_api_key)
        rec = (await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == h, ApiKey.revoked.is_(False),
            )
        )).scalar_one_or_none()
        if rec is None:
            raise AuthenticationError("Invalid API key.")
        rec.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        user_id = rec.user_id
    elif authorization:
        token = require_bearer(authorization)
        try:
            payload = decode_token(token)
        except Exception:
            raise AuthenticationError("Invalid token.")
        if payload.get("type") != "access":
            raise AuthenticationError("Not an access token.")
        user_id = payload["sub"]
    else:
        raise AuthenticationError("Credentials required.")

    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise AuthenticationError("User inactive or not found.")
    return user


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_router(request: Request) -> RequestRouter:
    return request.app.state.router
