import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditEvent

logger = logging.getLogger("xa.audit")


async def record(
    db: AsyncSession, *, actor_id: str | None, action: str,
    resource_type: str | None = None, resource_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(AuditEvent(
        actor_id=actor_id, action=action,
        resource_type=resource_type, resource_id=resource_id,
        meta=meta or {},
    ))
    await db.commit()
    logger.info("audit", extra={
        "actor_id": actor_id, "action": action,
        "resource_type": resource_type, "resource_id": resource_id,
    })
