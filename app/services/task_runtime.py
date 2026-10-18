import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, NotFound
from app.core.metrics import agent_runs_total, agent_steps_total
from app.database.models import Approval, Task, TaskRun, ToolCall
from app.orchestration.router import RequestRouter
from app.services.tools import execute_tool, requires_approval, tools_catalog

logger = logging.getLogger("xa.task_runtime")
_s = get_settings()


_SYSTEM = """You are XA Agent, a careful automation assistant.
You solve the user's task by reasoning step by step and calling tools.
Respond with a JSON object on each step:

{"thought": "...", "tool": "<name>" or null, "arguments": {...}, "final": null or {...}}

Rules:
- Only call tools in ALLOWED_TOOLS.
- If the task is complete, set "tool": null and "final": {<answer>}.
- Never invent tool output.
- If a tool errors, adapt your plan; don't repeat the same call more than twice.
"""


async def _build_prompt(task: Task, run: TaskRun, allowed: list[str]) -> list[dict]:
    catalog = [t for t in tools_catalog() if t.get("name") in allowed]
    return [
        {"role": "system", "content": _SYSTEM +
         f"\nALLOWED_TOOLS: {allowed}\nTOOLS_SCHEMA: {json.dumps(catalog)}"},
        {"role": "user", "content": (
            f"TASK: {task.name}\nDESCRIPTION: {task.description or ''}\n"
            f"INPUT: {json.dumps(run.input_data)}\n"
            f"STEPS_SO_FAR: {json.dumps(run.steps_log)}"
        )},
    ]


async def _create_approval(
    db: AsyncSession, run: TaskRun, tool: str, arguments: dict,
) -> Approval:
    a = Approval(
        user_id=run.user_id, run_id=run.id,
        tool_name=tool, arguments=arguments, status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db.add(a)
    await db.flush()
    run.pending_approval_id = a.id
    run.status = "waiting_approval"
    await db.commit()
    return a


async def _apply_tool_result(
    db: AsyncSession, run: TaskRun, step_index: int, tool: str,
    arguments: dict, result: dict, error: str | None,
) -> None:
    db.add(ToolCall(
        run_id=run.id, step_index=step_index, tool_name=tool,
        arguments=arguments, result=result, error=error,
        status="failed" if error else "completed",
    ))
    log = list(run.steps_log or [])
    log.append({
        "step": step_index, "tool": tool, "arguments": arguments,
        "result": result if not error else None, "error": error,
    })
    run.steps_log = log
    run.current_step = step_index + 1
    await db.commit()
    try:
        agent_steps_total.labels(tool=tool).inc()
    except Exception:
        pass


async def step(
    db: AsyncSession, run: TaskRun, task: Task, router: RequestRouter,
    *, resume_approval: Approval | None = None,
) -> str:
    allowed = [t for t in (task.allowed_tools or []) if t in _s.agent_allowed_tools]

    if resume_approval is not None:
        if resume_approval.status == "denied":
            run.status = "failed"
            run.error_code = "APPROVAL_DENIED"
            run.pending_approval_id = None
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return run.status
        result = await execute_tool(
            resume_approval.tool_name, resume_approval.arguments,
            context={"_db": db, "_user_id": run.user_id, "_router": router},
        )
        err = result.get("error") if isinstance(result, dict) else None
        await _apply_tool_result(
            db, run, run.current_step, resume_approval.tool_name,
            resume_approval.arguments, result, err,
        )
        run.pending_approval_id = None
        run.status = "running"
        await db.commit()
        return run.status

    if run.current_step >= min(task.max_steps, _s.agent_max_steps):
        run.status = "failed"
        run.error_code = "MAX_STEPS"
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return run.status

    messages = await _build_prompt(task, run, allowed)
    try:
        raw = await router.registry.find_ready("text").generate(
            messages, temperature=0.2, max_tokens=1500,
        )
        parsed = json.loads(raw["content"])
    except Exception as exc:
        logger.warning("agent_llm_failed", extra={"error": str(exc)})
        run.status = "failed"
        run.error_code = "AGENT_LLM_ERROR"
        run.error_detail = str(exc)[:500]
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return run.status

    tool = parsed.get("tool")
    final = parsed.get("final")
    thought = parsed.get("thought", "")
    arguments = parsed.get("arguments") or {}

    if tool is None:
        run.output = final or {"result": thought}
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return run.status

    if tool not in allowed:
        await _apply_tool_result(
            db, run, run.current_step, tool, arguments,
            {"error": "tool not allowed"}, "TOOL_NOT_ALLOWED",
        )
        return run.status

    if requires_approval(tool):
        await _create_approval(db, run, tool, arguments)
        return run.status

    result = await execute_tool(
        tool, arguments,
        context={"_db": db, "_user_id": run.user_id, "_router": router},
    )
    err = result.get("error") if isinstance(result, dict) else None
    await _apply_tool_result(db, run, run.current_step, tool, arguments, result, err)
    return run.status


async def run_to_completion(
    db: AsyncSession, run_id: str, router: RequestRouter,
) -> None:
    run = await db.get(TaskRun, run_id)
    if run is None:
        return
    task = await db.get(Task, run.task_id)
    if task is None:
        run.status = "failed"
        run.error_code = "TASK_NOT_FOUND"
        await db.commit()
        return

    if run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
        run.status = "running"
        await db.commit()

    while run.status in ("queued", "running"):
        elapsed = (datetime.now(timezone.utc) - run.started_at).total_seconds()
        if elapsed > _s.agent_run_timeout_seconds:
            run.status = "failed"
            run.error_code = "RUN_TIMEOUT"
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return
        new_status = await step(db, run, task, router)
        if new_status in ("succeeded", "failed", "waiting_approval", "cancelled"):
            try:
                agent_runs_total.labels(status=new_status).inc()
            except Exception:
                pass
            return


async def resume_after_approval(
    db: AsyncSession, approval_id: str, decision: str, decided_by: str,
    router: RequestRouter,
) -> TaskRun:
    """Record the decision, run ONLY the approved tool, then hand the run back
    to the queue so agent_worker continues it. The API request never runs the
    agent loop itself."""
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise NotFound("Approval not found.")
    now = datetime.now(timezone.utc)
    # Atomic claim of the decision: two concurrent decides cannot both win.
    res = await db.execute(
        update(Approval)
        .where(
            Approval.id == approval_id, Approval.status == "pending",
            Approval.expires_at > now,
        )
        .values(
            status="approved" if decision == "approve" else "denied",
            decided_by=decided_by, decided_at=now,
        )
    )
    await db.commit()
    if res.rowcount == 0:
        raise ConflictError("Approval already decided or expired.")
    await db.refresh(approval)

    run = await db.get(TaskRun, approval.run_id)
    task = await db.get(Task, run.task_id)
    await step(db, run, task, router, resume_approval=approval)
    if run.status == "running":
        run.status = "queued"
        await db.commit()
    return run
