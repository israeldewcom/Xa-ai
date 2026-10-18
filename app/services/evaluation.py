import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ModelEvaluation

logger = logging.getLogger("xa.evaluation")


async def run_evaluation(
    db: AsyncSession, *, model_id: str, dataset_version: str,
    evaluation_type: str, config: dict[str, Any],
) -> ModelEvaluation:
    ev = ModelEvaluation(
        model_id=model_id, dataset_version=dataset_version,
        evaluation_type=evaluation_type, metrics={}, status="running",
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    ev.metrics = {"note": "evaluation backend not wired"}
    ev.status = "completed"
    await db.commit()
    return ev
