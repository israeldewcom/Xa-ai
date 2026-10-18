"""Transactional outbox. claim_batch sets claimed_at; the reaper reclaims
stuck 'delivering' rows whose lease has expired."""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import OutboxEvent

logger = logging.getLogger("xa.outbox")
_s = get_settings()


async def enqueue(
    db: AsyncSession, user_id: str, event: str, payload: dict,
) -> OutboxEvent:
    ev = OutboxEvent(
        user_id=user_id, event=event,
        payload=json.dumps(payload, separators=(",", ":"), default=str),
        status="pending",
        attempts=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(ev)
    return ev


async def claim_batch(db: AsyncSession, limit: int) -> list[OutboxEvent]:
    """Claim a batch of events. Rows in 'delivering' whose claimed_at is
    older than the lease are re-eligible (crash recovery)."""
    now = datetime.now(timezone.utc)
    lease_cutoff = now - timedelta(seconds=_s.webhook_outbox_lease_seconds)

    stmt = (
        select(OutboxEvent)
        .where(
            or_(
                and_(
                    OutboxEvent.status.in_(("pending", "retry")),
                    OutboxEvent.next_attempt_at <= now,
                ),
                and_(
                    OutboxEvent.status == "delivering",
                    OutboxEvent.claimed_at.is_not(None),
                    OutboxEvent.claimed_at < lease_cutoff,
                ),
            )
        )
        .order_by(OutboxEvent.next_attempt_at)
        .limit(limit)
    )
    try:
        stmt = stmt.with_for_update(skip_locked=True)
    except Exception:
        pass
    rows = (await db.execute(stmt)).scalars().all()
    for r in rows:
        r.status = "delivering"
        r.claimed_at = now
    await db.commit()
    return rows


async def mark_delivered(db: AsyncSession, event_id: str) -> None:
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(
            status="delivered", delivered_at=datetime.now(timezone.utc),
            claimed_at=None,
        )
    )
    await db.commit()


async def mark_retry(
    db: AsyncSession, event_id: str, error: str, backoff_seconds: int,
) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(
            status="retry",
            attempts=OutboxEvent.attempts + 1,
            last_error=error[:500],
            next_attempt_at=now + timedelta(seconds=backoff_seconds),
            claimed_at=None,
        )
    )
    await db.commit()


async def mark_failed(db: AsyncSession, event_id: str, error: str) -> None:
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(status="failed", last_error=error[:500], claimed_at=None)
    )
    await db.commit()
