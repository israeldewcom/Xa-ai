import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.config import get_settings
from app.database.models import TaskRun, WorkerHeartbeat
from app.database.session import AsyncSessionLocal
from app.orchestration.registry import ModelRegistry
from app.orchestration.router import RequestRouter
from app.services.model_manager import bootstrap_registry
from app.services.task_runtime import run_to_completion

logger = logging.getLogger("xa.agent_worker")
_s = get_settings()


class AgentWorker:
    def __init__(self) -> None:
        self.worker_id = "agent-worker-" + uuid.uuid4().hex[:6]
        self._stop = asyncio.Event()
        self.router: RequestRouter | None = None

    async def _ensure_router(self) -> RequestRouter:
        if self.router is None:
            reg = ModelRegistry()
            await bootstrap_registry(reg)
            self.router = RequestRouter(reg)
        return self.router

    async def _heartbeat(self) -> None:
        while not self._stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    hb = await db.get(WorkerHeartbeat, self.worker_id)
                    now = datetime.now(timezone.utc)
                    if hb is None:
                        db.add(WorkerHeartbeat(
                            worker_id=self.worker_id,
                            worker_kind="agent_worker", last_seen=now,
                        ))
                    else:
                        hb.last_seen = now
                    await db.commit()
            except Exception:
                pass
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=_s.worker_heartbeat_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def _claim(self) -> TaskRun | None:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(TaskRun.id).where(TaskRun.status == "queued")
                .order_by(TaskRun.created_at).limit(1)
                .with_for_update(skip_locked=True)  # no-op on SQLite
            )).scalar_one_or_none()
            if row is None:
                return None
            res = await db.execute(
                update(TaskRun)
                .where(TaskRun.id == row, TaskRun.status == "queued")
                .values(
                    status="running",
                    # keep the original start so a resumed run's timeout budget
                    # is not silently reset
                    started_at=func.coalesce(
                        TaskRun.started_at, datetime.now(timezone.utc),
                    ),
                )
            )
            await db.commit()
            if res.rowcount == 0:
                return None
            return await db.get(TaskRun, row)

    async def run(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._stop.set)
                except (NotImplementedError, RuntimeError):
                    pass
        except RuntimeError:
            pass
        logger.info("agent_worker_start", extra={"worker_id": self.worker_id})
        router = await self._ensure_router()
        hb_task = asyncio.create_task(self._heartbeat())
        try:
            while not self._stop.is_set():
                try:
                    run = await self._claim()
                except Exception:
                    logger.exception("agent_claim_error")
                    await asyncio.sleep(_s.worker_poll_interval_seconds)
                    continue
                if run is None:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(),
                            timeout=_s.worker_poll_interval_seconds,
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue
                try:
                    async with AsyncSessionLocal() as db:
                        await run_to_completion(db, run.id, router)
                except Exception:
                    logger.exception("agent_run_error", extra={"run_id": run.id})
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass


async def main() -> None:
    await AgentWorker().run()


if __name__ == "__main__":
    from app.core.logging import setup_logging
    setup_logging("INFO")
    asyncio.run(main())
