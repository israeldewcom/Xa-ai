from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import CapabilityUnavailable, NotFound, ValidationFailure
from app.core.quotas import enforce
from app.database.models import Approval, ScheduledTask, Task, TaskRun, User
from app.database.session import get_db
from app.dependencies import get_current_user, get_router
from app.orchestration.router import RequestRouter
from app.schemas.tasks import (
    ApprovalDecision, ApprovalResponse, ScheduleCreate, TaskCreate,
    TaskResponse, TaskRunCreate, TaskRunResponse, ToolCallResponse,
)
from app.services.task_runtime import resume_after_approval

router = APIRouter(tags=["tasks"])
_s = get_settings()


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _s.automation_enabled:
        raise CapabilityUnavailable("automation")
    allowed = [t for t in payload.allowed_tools if t in _s.agent_allowed_tools]
    if not allowed:
        raise ValidationFailure("No allowed tools; automation requires at least one.")
    t = Task(
        user_id=user.id, name=payload.name, description=payload.description,
        input_schema=payload.input_schema, allowed_tools=allowed,
        max_steps=min(payload.max_steps, _s.agent_max_steps),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return TaskResponse.model_validate(t)


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc())
    )).scalars().all()
    return [TaskResponse.model_validate(t) for t in rows]


@router.post("/tasks/runs", response_model=TaskRunResponse, status_code=202)
async def start_run(
    payload: TaskRunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue a task run. Returns 202 with the run_id; the agent_worker
    processes it asynchronously. Poll via GET /tasks/runs/{id}."""
    await enforce(db, user.id, "agent_runs", 1)
    task = await db.get(Task, payload.task_id)
    if task is None or task.user_id != user.id:
        raise NotFound("Task not found.")
    run = TaskRun(
        task_id=task.id, user_id=user.id,
        input_data=payload.input_data, status="queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return TaskRunResponse.model_validate(run)


@router.get("/tasks/runs/{run_id}", response_model=TaskRunResponse)
async def get_run(
    run_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(TaskRun, run_id)
    if run is None or (run.user_id != user.id and user.role != "admin"):
        raise NotFound("Run not found.")
    return TaskRunResponse.model_validate(run)


@router.get("/tasks/runs/{run_id}/tool-calls", response_model=list[ToolCallResponse])
async def list_tool_calls(
    run_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(TaskRun, run_id)
    if run is None or (run.user_id != user.id and user.role != "admin"):
        raise NotFound("Run not found.")
    from app.database.models import ToolCall
    rows = (await db.execute(
        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.step_index)
    )).scalars().all()
    return [ToolCallResponse.model_validate(t) for t in rows]


@router.post("/tasks/runs/{run_id}/cancel", response_model=TaskRunResponse)
async def cancel_run(
    run_id: str, user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await db.get(TaskRun, run_id)
    if run is None or (run.user_id != user.id and user.role != "admin"):
        raise NotFound("Run not found.")
    if run.status in ("queued", "running", "waiting_approval"):
        run.status = "cancelled"
        from datetime import datetime, timezone
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
    return TaskRunResponse.model_validate(run)


@router.get("/approvals", response_model=list[ApprovalResponse])
async def list_approvals(
    status: str = "pending",
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Approval).where(
            Approval.user_id == user.id, Approval.status == status,
        ).order_by(Approval.created_at.desc())
    )).scalars().all()
    return [ApprovalResponse.model_validate(a) for a in rows]


@router.post("/approvals/{approval_id}/decide", response_model=TaskRunResponse)
async def decide_approval(
    approval_id: str, payload: ApprovalDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    router_dep: RequestRouter = Depends(get_router),
):
    approval = await db.get(Approval, approval_id)
    if approval is None or approval.user_id != user.id:
        raise NotFound("Approval not found.")
    run = await resume_after_approval(
        db, approval_id, payload.decision, user.id, router_dep,
    )
    return TaskRunResponse.model_validate(run)


@router.post("/tasks/schedules", status_code=201)
async def create_schedule(
    payload: ScheduleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from croniter import croniter
    from datetime import datetime, timezone
    if not croniter.is_valid(payload.cron):
        raise ValidationFailure("Invalid cron expression.")
    task = await db.get(Task, payload.task_id)
    if task is None or task.user_id != user.id:
        raise NotFound("Task not found.")
    now = datetime.now(timezone.utc)
    next_run = croniter(payload.cron, now).get_next(datetime).replace(
        tzinfo=timezone.utc,
    )
    sched = ScheduledTask(
        user_id=user.id, task_id=task.id, cron=payload.cron,
        input_data=payload.input_data, next_run_at=next_run,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    return {"id": sched.id, "next_run_at": sched.next_run_at}
