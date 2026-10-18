"""Daily quotas — atomic conditional UPDATE, safe under concurrency."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import RateLimited
from app.core.metrics import quota_rejections_total
from app.database.models import DailyQuota

_s = get_settings()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def check_and_increment(
    db: AsyncSession, user_id: str, key: str, amount: int, limit: int,
) -> int:
    """Atomic check+increment. A conditional UPDATE is atomic on PostgreSQL and
    SQLite alike, so concurrent requests can never overshoot the limit."""
    today = _today_utc()
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as ins
    else:
        from sqlalchemy.dialects.sqlite import insert as ins

    await db.execute(
        ins(DailyQuota)
        .values(id=uuid.uuid4().hex, user_id=user_id, day=today, key=key, used=0)
        .on_conflict_do_nothing(index_elements=["user_id", "day", "key"])
    )

    where = (
        DailyQuota.user_id == user_id, DailyQuota.day == today,
        DailyQuota.key == key,
    )
    res = await db.execute(
        update(DailyQuota)
        .where(*where, DailyQuota.used + amount <= limit)
        .values(used=DailyQuota.used + amount)
        .returning(DailyQuota.used)
    )
    row = res.first()
    if row is None:
        used = (await db.execute(select(DailyQuota.used).where(*where))).scalar_one()
        await db.commit()
        reset_at = datetime.strptime(today, "%Y-%m-%d").replace(
            tzinfo=timezone.utc) + timedelta(days=1)
        retry = max(1, int((reset_at - datetime.now(timezone.utc)).total_seconds()))
        try:
            quota_rejections_total.labels(key=key).inc()
        except Exception:
            pass
        raise RateLimited(
            f"Daily quota '{key}' exceeded ({used}/{limit}). Resets in {retry}s.",
            retry_after=retry,
        )
    await db.commit()
    return row[0]


async def get_today(db: AsyncSession, user_id: str) -> dict[str, int]:
    today = _today_utc()
    rows = (await db.execute(
        select(DailyQuota).where(
            DailyQuota.user_id == user_id, DailyQuota.day == today,
        )
    )).scalars().all()
    return {r.key: r.used for r in rows}


async def enforce(db: AsyncSession, user_id: str, key: str, amount: int = 1) -> None:
    limits = {
        "chat": _s.quota_chat_per_day,
        "chat_tokens": _s.quota_chat_tokens_per_day,
        "upload_bytes": _s.quota_upload_mb_per_day * 1024 * 1024,
        "jobs": _s.quota_jobs_per_day,
        "agent_runs": _s.quota_agent_runs_per_day,
        "voice_seconds": _s.quota_voice_minutes_per_day * 60,
    }
    limit = limits.get(key)
    if limit is None:
        return
    await check_and_increment(db, user_id, key, amount, limit)
