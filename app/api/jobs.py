import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, PermissionDenied
from app.core.quotas import enforce
from app.database.models import Job, User
from app.database.session import get_db
from app.dependencies import get_current_user
from app.schemas.jobs import JobCreate, JobResponse
from app.schemas.pagination import Page
from app.services.pagination import apply_cursor, encode_cursor

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    payload: JobCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce(db, user.id, "jobs", 1)
    input_ref: str | None = payload.input_reference
    if payload.parameters:
        input_ref = json.dumps({
            "reference": payload.input_reference,
            "parameters": payload.parameters,
        })
    job = Job(
        user_id=user.id, job_type=payload.job_type,
        input_reference=input_ref, status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return JobResponse.model_validate(job)


@router.get("", response_model=Page[JobResponse])
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = apply_cursor(
        select(Job).where(Job.user_id == user.id), Job, cursor,
    ).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page(
        items=[JobResponse.model_validate(j) for j in items],
        next_cursor=next_cursor,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found.")
    if job.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your job.")
    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found.")
    if job.user_id != user.id and user.role != "admin":
        raise PermissionDenied("Not your job.")
    if job.status in ("queued", "running"):
        job.status = "cancelled"
        await db.commit()
    return JobResponse.model_validate(job)
