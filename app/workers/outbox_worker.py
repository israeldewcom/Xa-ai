import asyncio
import json
import logging
import signal

from app.config import get_settings
from app.core.outbox import (
    claim_batch, mark_delivered, mark_failed, mark_retry,
)
from app.core.webhooks import deliver_outbox_event
from app.database.models import WorkerHeartbeat
from app.database.session import AsyncSessionLocal
from app.database.models import WorkerHeartbeat
from datetime import datetime, timezone

logger = logging.getLogger("xa.outbox_worker")
_s = get_settings()
WORKER_ID = "outbox-worker"


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as db:
                hb = await db.get(WorkerHeartbeat, WORKER_ID)
                now = datetime.now(timezone.utc)
                if hb is None:
                    db.add(WorkerHeartbeat(
                        worker_id=WORKER_ID, worker_kind="outbox_worker",
                        last_seen=now,
                    ))
                else:
                    hb.last_seen = now
                await db.commit()
        except Exception as exc:
            logger.warning("hb_failed", extra={"error": str(exc)})
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
    logger.info("outbox_worker_start")
    try:
        while not stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    events = await claim_batch(db, _s.webhook_outbox_batch)
                    if not events:
                        try:
                            await asyncio.wait_for(
                                stop.wait(),
                                timeout=_s.webhook_outbox_interval,
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                    for ev in events:
                        payload = json.loads(ev.payload)
                        try:
                            ok, fail = await deliver_outbox_event(
                                db, ev.user_id, ev.event, payload,
                            )
                            if fail == 0:
                                await mark_delivered(db, ev.id)
                            elif ev.attempts + 1 >= _s.webhook_max_retries:
                                await mark_failed(db, ev.id, f"{fail} failures")
                            else:
                                await mark_retry(
                                    db, ev.id, f"{fail} failures",
                                    backoff_seconds=2 ** (ev.attempts + 1),
                                )
                        except Exception as exc:
                            logger.exception(
                                "outbox_delivery_error",
                                extra={"event_id": ev.id},
                            )
                            await mark_retry(
                                db, ev.id, str(exc), backoff_seconds=10,
                            )
            except Exception:
                logger.exception("outbox_loop_error")
                await asyncio.sleep(5)
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
