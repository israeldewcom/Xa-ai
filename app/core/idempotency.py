"""Idempotency with TTL enforcement and safe race handling."""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError
from app.database.models import IdempotencyRecord

logger = logging.getLogger("xa.idempotency")
_s = get_settings()


class IdempotencyManager:
    def __init__(self, db: AsyncSession, user_id: str, route: str):
        self.db = db
        self.user_id = user_id
        self.route = route

    async def begin(self, key: str) -> dict | None:
        existing = await self._get(key)
        if existing is None:
            self.db.add(IdempotencyRecord(
                user_id=self.user_id, key=key, route=self.route,
                status_code=None, body="",
                expires_at=datetime.now(timezone.utc) + timedelta(
                    seconds=_s.idempotency_ttl_seconds
                ),
            ))
            try:
                await self.db.commit()
                return None
            except IntegrityError:
                await self.db.rollback()
                existing = await self._get(key)
        if existing is None:
            raise ConflictError("Idempotency race lost; retry.")
        if existing.status_code is None:
            raise ConflictError(
                "Request with this Idempotency-Key is still in progress."
            )
        return {"status_code": existing.status_code, "body": json.loads(existing.body)}

    async def finalize(self, key: str, status_code: int, body: dict) -> None:
        rec = await self._get(key)
        if rec is None:
            return
        rec.status_code = status_code
        rec.body = json.dumps(body, default=str)
        await self.db.commit()

    async def release(self, key: str) -> None:
        rec = await self._get(key)
        if rec is not None and rec.status_code is None:
            await self.db.delete(rec)
            await self.db.commit()

    async def _get(self, key: str) -> IdempotencyRecord | None:
        now = datetime.now(timezone.utc)
        stmt = select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == self.user_id,
            IdempotencyRecord.route == self.route,
            IdempotencyRecord.key == key,
            IdempotencyRecord.expires_at > now,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


async def purge_expired(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    res = await db.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
    )
    await db.commit()
    return res.rowcount or 0
