import asyncio
import logging
import signal

from app.config import get_settings
from app.database.models import WorkerHeartbeat
from app.database.session import AsyncSessionLocal
from app.services.scheduler import tick
from datetime import datetime, timezone

logger = logging.getLogger("xa.scheduler_worker")
_s = get_settings()
WORKER_ID = "scheduler-worker"


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as db:
                hb = await db.get(WorkerHeartbeat, WORKER_ID)
                now = datetime.now(timezone.utc)
                if hb is None:
                    db.add(WorkerHeartbeat(
                        worker_id=WORKER_ID, worker_kind="scheduler_worker",
                        last_seen=now,
                    ))
                else:
                    hb.last_seen = now
                await db.commit()
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=_s.worker_heartbeat_seconds,
            )
        except asyncio.TimeoutError:
            pass


async def run() -> None:
    stop = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
    except RuntimeError:
        pass

    hb_task = asyncio.create_task(_heartbeat(stop))
    logger.info("scheduler_start")
    try:
        while not stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    n = await tick(db)
                    if n:
                        logger.info("scheduler_tick", extra={"created": n})
            except Exception:
                logger.exception("scheduler_error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    from app.core.logging import setup_logging
    setup_logging("INFO")
    asyncio.run(run())
