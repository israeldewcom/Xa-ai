from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import CapabilityUnavailable, NotFound, PermissionDenied
from app.database.models import TrainingRun, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.training import TrainingCreate, TrainingResponse

router = APIRouter(prefix="/training", tags=["training"])
_s = get_settings()


@router.post("", response_model=TrainingResponse, status_code=201)
async def start_training(
    payload: TrainingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _s.training_enabled:
        raise CapabilityUnavailable("training")
    run = TrainingRun(
        user_id=user.id, model_id=payload.model_id,
        dataset_reference=payload.dataset_reference,
        training_method=payload.training_method,
        configuration=payload.configuration, status="queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return TrainingResponse.model_validate(run)


@router.get("", response_model=list[TrainingResponse])
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(TrainingRun).where(TrainingRun.user_id == user.id)
    )).scalars().all()
    return [TrainingResponse.model_validate(r) for r in rows]


@router.get("/{run_id}", response_model=TrainingResponse)
async def get_run(
    run_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(TrainingRun, run_id)
    if run is None:
        raise NotFound("Training run not found.")
    if run.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your run.")
    return TrainingResponse.model_validate(run)
