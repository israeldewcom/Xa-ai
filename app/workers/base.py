import asyncio
import logging
import random
import signal
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.metrics import jobs_in_flight, jobs_total
from app.core.outbox import enqueue as outbox_enqueue
from app.database.models import Job, WorkerHeartbeat
from app.database.session import AsyncSessionLocal

logger = logging.getLogger("xa.worker")
_s = get_settings()


class BaseWorker:
    job_types: tuple[str, ...] = ()
    poll_interval: float = _s.worker_poll_interval_seconds
    lease_seconds: int = _s.worker_lease_seconds
    heartbeat_interval: int = _s.worker_heartbeat_seconds

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self.worker_id = f"{self.__class__.__name__}-{uuid.uuid4().hex[:8]}"
        self._current_job_id: str | None = None

    def install_signal_handlers(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except (NotImplementedError, RuntimeError):
                pass

    async def handle(self, job: Job) -> tuple[str, str]:
        raise NotImplementedError

    def _dialect_name(self, db: AsyncSession) -> str:
        try:
            return db.get_bind().dialect.name
        except Exception:
            return ""

    async def _reclaim_stale(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.lease_seconds)
        async with AsyncSessionLocal() as db:
            stmt = (
                update(Job)
                .where(
                    Job.job_type.in_(self.job_types),
                    Job.status == "running",
                    Job.started_at < cutoff,
                )
                .values(status="queued", started_at=None, progress=0)
            )
            res = await db.execute(stmt)
            await db.commit()
            if res.rowcount:
                logger.warning("reclaimed_stale", extra={"count": res.rowcount})

    async def _claim_one(self) -> Job | None:
        async with AsyncSessionLocal() as db:
            dialect = self._dialect_name(db)
            now = datetime.now(timezone.utc)

            elig = (
                Job.job_type.in_(self.job_types),
                Job.status == "queued",
                Job.dead_lettered.is_(False),
                # Phase 0.2: honor next_attempt_at. NULL means ready-now.
                or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
            )

            if dialect == "postgresql":
                stmt = (
                    select(Job)
                    .where(*elig)
                    .order_by(Job.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                job = (await db.execute(stmt)).scalar_one_or_none()
                if job is None:
                    return None
                job.status = "running"
                job.started_at = now
                job.attempts = (job.attempts or 0) + 1
                await db.commit()
                await db.refresh(job)
                return job

            row = (await db.execute(
                select(Job.id)
                .where(*elig)
                .order_by(Job.created_at)
                .limit(1)
            )).scalar_one_or_none()
            if row is None:
                return None
            result = await db.execute(
                update(Job)
                .where(Job.id == row, Job.status == "queued")
                .values(
                    status="running", started_at=now,
                    attempts=Job.attempts + 1,
                )
            )
            await db.commit()
            if result.rowcount == 0:
                return None
            return await db.get(Job, row)

    async def _finish(
        self, job_id: str, status: str, output: str | None = None,
        error_code: str | None = None, error_detail: str | None = None,
    ) -> tuple[str, str]:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            if job is None:
                return ("", "")
            job.output_reference = output
            job.error_code = error_code
            job.error_detail = error_detail
            event_name = "job.completed"

            if status == "succeeded":
                job.status = "succeeded"
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                job.next_attempt_at = None
            else:
                max_attempts = job.max_attempts or _s.job_max_attempts
                if (job.attempts or 0) >= max_attempts:
                    job.status = "failed"
                    job.dead_lettered = True
                    job.finished_at = datetime.now(timezone.utc)
                    event_name = "job.dead_lettered"
                else:
                    job.status = "queued"
                    job.started_at = None
                    backoff = _s.job_backoff_base_seconds * (
                        2 ** ((job.attempts or 1) - 1)
                    )
                    jitter = random.uniform(0, _s.job_backoff_jitter_seconds)
                    job.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                        seconds=backoff + jitter,
                    )
                    event_name = "job.failed"

            user_id = job.user_id
            job_type = job.job_type
            job_pk = job.id
            await outbox_enqueue(db, user_id, event_name, {
                "job_id": job_pk, "job_type": job_type,
                "status": job.status, "error_code": job.error_code,
            })
            await db.commit()

        try:
            jobs_total.labels(job_type=job_type, status=status).inc()
        except Exception:
            pass
        return (output or "", error_code or "")

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with AsyncSessionLocal() as db:
                    hb = await db.get(WorkerHeartbeat, self.worker_id)
                    now = datetime.now(timezone.utc)
                    if hb is None:
                        db.add(WorkerHeartbeat(
                            worker_id=self.worker_id,
                            worker_kind=self.__class__.__name__.replace("Worker", "").lower() + "_worker",
                            last_seen=now, current_job_id=self._current_job_id,
                        ))
                    else:
                        hb.last_seen = now
                        hb.current_job_id = self._current_job_id
                    await db.commit()
            except Exception as exc:
                logger.warning("heartbeat_failed", extra={"error": str(exc)})
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.heartbeat_interval,
                )
            except asyncio.TimeoutError:
                pass

    async def run(self) -> None:
        self.install_signal_handlers()
        logger.info("worker_start", extra={
            "worker_id": self.worker_id, "types": list(self.job_types),
        })
        hb_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self._stop.is_set():
                try:
                    await self._reclaim_stale()
                except Exception:
                    logger.exception("reclaim_failed")
                try:
                    job = await self._claim_one()
                except Exception:
                    logger.exception("claim_failed")
                    await asyncio.sleep(self.poll_interval)
                    continue
                if job is None:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=self.poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue
                self._current_job_id = job.id
                jobs_in_flight.labels(job_type=job.job_type).inc()
                logger.info("job_started", extra={
                    "worker_id": self.worker_id, "job_id": job.id,
                    "type": job.job_type, "attempt": job.attempts,
                })
                try:
                    output, err = await self.handle(job)
                    if err:
                        await self._finish(job.id, "failed", error_code=err)
                    else:
                        await self._finish(job.id, "succeeded", output=output)
                except Exception as exc:
                    logger.exception("job_failed", extra={"job_id": job.id})
                    await self._finish(
                        job.id, "failed",
                        error_code="WORKER_ERROR", error_detail=str(exc),
                    )
                finally:
                    self._current_job_id = None
                    try:
                        jobs_in_flight.labels(job_type=job.job_type).dec()
                    except Exception:
                        pass
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("worker_stopped", extra={"worker_id": self.worker_id})
