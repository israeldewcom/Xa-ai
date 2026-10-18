from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.exceptions import NotFound, PermissionDenied
from app.core.rate_limit import RateLimiter
from app.database.models import User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise PermissionDenied("Admin only.")


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    limiter: RateLimiter = request.app.state.admin_limiter
    await limiter.check(f"admin:{user.id}")
    rows = (await db.execute(select(User))).scalars().all()
    return [UserResponse.model_validate(u) for u in rows]


@router.post("/users/{user_id}/suspend", response_model=UserResponse)
async def suspend_user(
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    target = await db.get(User, user_id)
    if target is None:
        raise NotFound("User not found.")
    target.status = "suspended"
    await db.commit()
    await audit_record(
        db, actor_id=user.id, action="admin.suspend_user",
        resource_type="user", resource_id=user_id,
    )
    return UserResponse.model_validate(target)


@router.post("/users/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    target = await db.get(User, user_id)
    if target is None:
        raise NotFound("User not found.")
    target.status = "active"
    await db.commit()
    await audit_record(
        db, actor_id=user.id, action="admin.activate_user",
        resource_type="user", resource_id=user_id,
    )
    return UserResponse.model_validate(target)


@router.delete("/users/{user_id}", status_code=204)
async def admin_erase_user(
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    from app.core.erasure import erase_user
    await erase_user(db, user_id, actor_id=user.id)
