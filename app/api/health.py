import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import WorkerHeartbeat
from app.database.session import get_db

router = APIRouter(tags=["health"])
_s = get_settings()
_started = time.monotonic()


@router.get("/health")
async def health():
    return {"status": "ok", "uptime_s": int(time.monotonic() - _started)}


@router.get("/health/live")
async def live():
    return {"status": "alive"}


EXPECTED_WORKERS = [
    "media_worker", "outbox_worker", "agent_worker",
    "scheduler_worker", "purge_worker",
]


async def _stale_workers(db: AsyncSession) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=_s.worker_heartbeat_seconds * 3
    )
    rows = (await db.execute(
        select(WorkerHeartbeat).where(WorkerHeartbeat.last_seen >= cutoff)
    )).scalars().all()
    seen = {r.worker_kind for r in rows}
    return [w for w in EXPECTED_WORKERS if w not in seen]


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness depends on the database only, so a stalled background worker
    can never take the API out of the load balancer."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "problems": ["database unavailable"]},
        )
    return {"status": "ready"}


@router.get("/health/workers")
async def workers(db: AsyncSession = Depends(get_db)):
    """Point alerting (not the load balancer) at this endpoint."""
    try:
        stale = await _stale_workers(db)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "stale": ["heartbeat check failed"]},
        )
    if stale:
        return JSONResponse(
            status_code=503, content={"status": "degraded", "stale": stale},
        )
    return {"status": "ok"}
