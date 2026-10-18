"""Webhook signing + delivery. Delivery is driven by the outbox worker."""
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.metrics import webhook_deliveries_total
from app.core.ssrf import validate_url_async
from app.database.models import Webhook

logger = logging.getLogger("xa.webhooks")
_s = get_settings()


def sign(secret: str, body: bytes, ts: str) -> str:
    msg = f"{ts}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


async def _matching_hooks(
    db: AsyncSession, user_id: str, event: str,
) -> list[Webhook]:
    rows = (await db.execute(
        select(Webhook).where(
            Webhook.user_id == user_id, Webhook.active.is_(True),
        )
    )).scalars().all()
    return [h for h in rows if event in (h.events or [])]


async def deliver_outbox_event(
    db: AsyncSession, user_id: str, event: str, payload: dict[str, Any],
) -> tuple[int, int]:
    """Deliver one outbox event to all matching hooks. Returns (success, fail).

    Fully async — no time.sleep, no blocking.
    """
    hooks = await _matching_hooks(db, user_id, event)
    if not hooks:
        return (0, 0)

    body = json.dumps(
        {"event": event, "data": payload}, separators=(",", ":"), default=str,
    ).encode()
    ts = str(int(time.time()))

    success, failure = 0, 0
    for hook in hooks:
        try:
            await validate_url_async(hook.url)
        except Exception as exc:
            logger.warning("webhook_url_blocked", extra={
                "hook_id": hook.id, "error": str(exc),
            })
            webhook_deliveries_total.labels(status="blocked").inc()
            failure += 1
            continue
        headers = {
            "Content-Type": "application/json",
            "X-XA-Event": event,
            "X-XA-Timestamp": ts,
            "X-XA-Signature": sign(hook.secret, body, ts),
        }
        try:
            async with httpx.AsyncClient(timeout=_s.webhook_timeout_seconds) as client:
                r = await client.post(hook.url, content=body, headers=headers)
            if 200 <= r.status_code < 300:
                success += 1
                webhook_deliveries_total.labels(status="success").inc()
            else:
                failure += 1
                webhook_deliveries_total.labels(status="failed").inc()
                logger.warning("webhook_non2xx", extra={
                    "hook_id": hook.id, "status": r.status_code,
                })
        except Exception as exc:
            failure += 1
            webhook_deliveries_total.labels(status="error").inc()
            logger.warning("webhook_exception", extra={
                "hook_id": hook.id, "error": str(exc),
            })
    return (success, failure)
