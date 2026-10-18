"""GDPR-grade account erasure — cascading delete of all user data.

Audit events are preserved (regulatory carve-out) but scrubbed of PII.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    ApiKey, Approval, AuditEvent, Conversation, Device, DeviceCommand,
    DevicePairing, DocumentChunk, DailyQuota, FileRecord, IdempotencyRecord,
    Job, Message, OutboxEvent, RefreshToken, ScheduledTask, Task, TaskRun,
    ToolCall, UsageEvent, User, VoiceSession, Webhook,
)
from app.services.storage import get_storage

logger = logging.getLogger("xa.erasure")


async def erase_user(db: AsyncSession, user_id: str, *, actor_id: str) -> dict:
    counts: dict[str, int] = {}

    async def _del(model, *conds):
        res = await db.execute(delete(model).where(*conds))
        counts[model.__tablename__] = res.rowcount or 0

    # Collect child IDs first — clean select() not db.query()
    conv_ids = (await db.execute(
        select(Conversation.id).where(Conversation.user_id == user_id)
    )).scalars().all()

    if conv_ids:
        await _del(Message, Message.conversation_id.in_(conv_ids))
    await _del(Conversation, Conversation.user_id == user_id)

    storage_keys = (await db.execute(
        select(FileRecord.storage_key).where(FileRecord.user_id == user_id)
    )).scalars().all()

    await _del(DocumentChunk, DocumentChunk.user_id == user_id)
    await _del(FileRecord, FileRecord.user_id == user_id)
    await _del(Job, Job.user_id == user_id)

    run_ids = (await db.execute(
        select(TaskRun.id).where(TaskRun.user_id == user_id)
    )).scalars().all()
    if run_ids:
        await _del(ToolCall, ToolCall.run_id.in_(run_ids))
        await _del(Approval, Approval.run_id.in_(run_ids))
    await _del(TaskRun, TaskRun.user_id == user_id)

    task_ids = (await db.execute(
        select(Task.id).where(Task.user_id == user_id)
    )).scalars().all()
    if task_ids:
        await _del(ScheduledTask, ScheduledTask.task_id.in_(task_ids))
    await _del(Task, Task.user_id == user_id)

    device_ids = (await db.execute(
        select(Device.id).where(Device.user_id == user_id)
    )).scalars().all()
    if device_ids:
        await _del(DeviceCommand, DeviceCommand.device_id.in_(device_ids))
        await _del(DevicePairing, DevicePairing.device_id.in_(device_ids))
    await _del(Device, Device.user_id == user_id)

    await _del(VoiceSession, VoiceSession.user_id == user_id)
    await _del(Webhook, Webhook.user_id == user_id)
    await _del(ApiKey, ApiKey.user_id == user_id)
    await _del(RefreshToken, RefreshToken.user_id == user_id)
    await _del(IdempotencyRecord, IdempotencyRecord.user_id == user_id)
    await _del(UsageEvent, UsageEvent.user_id == user_id)
    await _del(DailyQuota, DailyQuota.user_id == user_id)
    await _del(OutboxEvent, OutboxEvent.user_id == user_id)

    await db.execute(
        update(AuditEvent)
        .where(AuditEvent.actor_id == user_id)
        .values(
            actor_id=None,
            meta={"scrubbed": True, "erased_at": datetime.now(timezone.utc).isoformat()},
        )
    )

    db.add(AuditEvent(
        actor_id=actor_id, action="user.erase",
        resource_type="user", resource_id=user_id,
        meta={"counts": counts},
    ))

    await db.execute(delete(User).where(User.id == user_id))
    counts["users"] = 1

    await db.commit()

    # Delete stored objects after the commit so a DB failure can never leave
    # rows pointing at missing files.
    for key in storage_keys:
        try:
            await asyncio.to_thread(get_storage().delete, key)
        except Exception:
            logger.warning("erasure_file_delete_failed", extra={"key": key})
    counts["stored_objects"] = len(storage_keys)
    logger.info("user_erased", extra={"user_id": user_id, "counts": counts})
    return counts
