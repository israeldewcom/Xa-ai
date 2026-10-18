from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cost import aggregate
from app.core.quotas import get_today
from app.database.models import User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.quotas import QuotaStatus, UsageAggregate

router = APIRouter(tags=["account"])
_s = get_settings()


@router.get("/account/quotas", response_model=QuotaStatus)
async def quotas(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    used = await get_today(db, user.id)
    return QuotaStatus(
        chat=used.get("chat", 0),
        chat_tokens=used.get("chat_tokens", 0),
        upload_bytes=used.get("upload_bytes", 0),
        jobs=used.get("jobs", 0),
        agent_runs=used.get("agent_runs", 0),
        voice_seconds=used.get("voice_seconds", 0),
    )


@router.get("/account/quotas/limits")
async def quota_limits(user: User = Depends(get_current_user)):
    return {
        "chat": _s.quota_chat_per_day,
        "chat_tokens": _s.quota_chat_tokens_per_day,
        "upload_bytes": _s.quota_upload_mb_per_day * 1024 * 1024,
        "jobs": _s.quota_jobs_per_day,
        "agent_runs": _s.quota_agent_runs_per_day,
        "voice_seconds": _s.quota_voice_minutes_per_day * 60,
    }


@router.get("/account/usage", response_model=list[UsageAggregate])
async def usage(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    agg = await aggregate(db, user.id)
    return [UsageAggregate(kind=k, **v) for k, v in agg.items()]
