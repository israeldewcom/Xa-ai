"""Token accounting — per-call usage recorded, per-user aggregated."""
import logging
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pricing import cost_micros
from app.database.models import UsageEvent

logger = logging.getLogger("xa.cost")


async def record_usage(
    db: AsyncSession,
    user_id: str,
    *,
    kind: str,
    model_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_micros_override: int | None = None,
    extra: dict | None = None,
) -> None:
    total_cost = 0
    if cost_micros_override is not None:
        total_cost = cost_micros_override
    elif model_id and input_tokens is not None and output_tokens is not None:
        total_cost = cost_micros(model_id, input_tokens, output_tokens)

    db.add(UsageEvent(
        user_id=user_id, kind=kind, model_id=model_id,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_micros=total_cost, extra=extra or {},
    ))
    await db.commit()


async def aggregate(db: AsyncSession, user_id: str) -> dict:
    rows = (await db.execute(
        select(
            UsageEvent.kind,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0),
        ).where(UsageEvent.user_id == user_id).group_by(UsageEvent.kind)
    )).all()
    out = {}
    for kind, cnt, in_tok, out_tok, cost in rows:
        out[kind] = {
            "count": int(cnt),
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "cost_micros": int(cost),
        }
    return out
