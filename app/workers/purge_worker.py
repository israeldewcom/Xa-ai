"""Purges: idempotency, expired voice sessions, orphaned active voice
sessions, expired approvals (and fails their runs), messages, audit, quotas."""
import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.config import get_settings
from app.core.idempotency import purge_expired
from app.database.models import (
    Approval, AuditEvent, DailyQuota, DeviceCommand, Message, TaskRun, UsageEvent,
    VoiceSession, WorkerHeartbeat,
)
from app.database.session import AsyncSessionLocal

logger = logging.getLogger("xa.purge_worker")
_s = get_settings()
WORKER_ID = "purge-worker"


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as db:
                hb = await db.get(WorkerHeartbeat, WORKER_ID)
                now = datetime.now(timezone.utc)
                if hb is None:
                    db.add(WorkerHeartbeat(
                        worker_id=WORKER_ID, worker_kind="purge_worker",
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


async def tick() -> dict:
    now = datetime.now(timezone.utc)
    counts = {}
    async with AsyncSessionLocal() as db:
        counts["idempotency"] = await purge_expired(db)

        if _s.retention_voice_sessions_days > 0:
            cutoff = now - timedelta(days=_s.retention_voice_sessions_days)
            r = await db.execute(
                delete(VoiceSession).where(VoiceSession.ended_at < cutoff)
            )
            counts["voice_sessions"] = r.rowcount or 0

        # Orphaned active voice sessions
        orphan_cutoff = now - timedelta(seconds=_s.orphan_voice_session_seconds)
        r = await db.execute(
            update(VoiceSession)
            .where(
                VoiceSession.status == "active",
                VoiceSession.started_at < orphan_cutoff,
            )
            .values(status="abandoned", ended_at=now)
        )
        counts["orphaned_voice"] = r.rowcount or 0

        if _s.retention_messages_days > 0:
            cutoff = now - timedelta(days=_s.retention_messages_days)
            r = await db.execute(delete(Message).where(Message.created_at < cutoff))
            counts["messages"] = r.rowcount or 0

        if _s.retention_audit_days > 0:
            cutoff = now - timedelta(days=_s.retention_audit_days)
            r = await db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
            counts["audit"] = r.rowcount or 0

        # Expire approvals and fail their runs
        expired_ids_res = await db.execute(
            update(Approval)
            .where(
                Approval.status == "pending",
                Approval.expires_at < now,
            )
            .values(status="expired", decided_at=now)
            .returning(Approval.id)
        )
        expired_ids = [row[0] for row in expired_ids_res.fetchall()]
        counts["approvals_expired"] = len(expired_ids)
        if expired_ids:
            r = await db.execute(
                update(TaskRun)
                .where(
                    TaskRun.status == "waiting_approval",
                    TaskRun.pending_approval_id.in_(expired_ids),
                )
                .values(
                    status="failed", error_code="APPROVAL_EXPIRED",
                    finished_at=now, pending_approval_id=None,
                )
            )
            counts["runs_failed_by_approval_expiry"] = r.rowcount or 0

        # Device commands: delivered but unanswered past TTL -> retry or fail
        stale = now - timedelta(seconds=_s.device_command_ttl_seconds)
        r = await db.execute(
            update(DeviceCommand)
            .where(
                DeviceCommand.status == "delivered",
                DeviceCommand.delivered_at < stale,
                DeviceCommand.attempts < _s.device_command_max_attempts,
                DeviceCommand.expires_at > now,
            )
            .values(status="queued")
        )
        counts["device_commands_requeued"] = r.rowcount or 0
        r = await db.execute(
            update(DeviceCommand)
            .where(
                DeviceCommand.status.in_(("queued", "delivered")),
                DeviceCommand.expires_at < now,
            )
            .values(status="expired", finished_at=now)
        )
        counts["device_commands_expired"] = r.rowcount or 0

        cutoff = now - timedelta(days=90)
        r = await db.execute(delete(DailyQuota).where(DailyQuota.updated_at < cutoff))
        counts["daily_quotas"] = r.rowcount or 0
        r = await db.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff))
        counts["usage"] = r.rowcount or 0
        await db.commit()
    logger.info("purge_tick", extra=counts)
    return counts


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
    logger.info("purge_worker_start")
    try:
        while not stop.is_set():
            try:
                await tick()
            except Exception:
                logger.exception("purge_error")
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=_s.purge_interval_seconds,
                )
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
