import logging
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ScheduledTask, Task, TaskRun

logger = logging.getLogger("xa.scheduler")


def _next_run(cron: str, after: datetime) -> datetime:
    it = croniter(cron, after)
    return it.get_next(datetime).replace(tzinfo=timezone.utc)


async def tick(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(ScheduledTask).where(
            ScheduledTask.enabled.is_(True),
            ScheduledTask.next_run_at <= now,
        )
    )).scalars().all()
    for sched in rows:
        task = await db.get(Task, sched.task_id)
        if task is None or not task.enabled:
            sched.enabled = False
            await db.commit()
            continue
        db.add(TaskRun(
            task_id=task.id, user_id=sched.user_id,
            input_data=sched.input_data or {}, status="queued",
        ))
        sched.last_run_at = now
        sched.next_run_at = _next_run(sched.cron, now)
        await db.commit()
    return len(rows)
