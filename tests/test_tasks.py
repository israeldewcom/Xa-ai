async def test_task_requires_allowed_tools(auth_client):
    r = await auth_client.post("/api/v1/tasks", json={
        "name": "t", "allowed_tools": ["does_not_exist"],
    })
    assert r.status_code == 422


async def test_agent_run_returns_202_queued(auth_client):
    """Phase 1.4: runs are enqueued, not executed inline."""
    r = await auth_client.post("/api/v1/tasks", json={
        "name": "calc", "allowed_tools": ["math"], "max_steps": 3,
    })
    assert r.status_code == 201
    task_id = r.json()["id"]

    r = await auth_client.post("/api/v1/tasks/runs", json={
        "task_id": task_id, "input_data": {"q": "2+2"},
    })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    run_id = body["id"]

    # Poll returns the current state without blocking
    r = await auth_client.get(f"/api/v1/tasks/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["id"] == run_id


async def test_approval_expiry_fails_run(app):
    """Expired approvals cause the purge worker to fail the associated run."""
    from datetime import datetime, timedelta, timezone
    from app.database.models import (
        Approval, Task, TaskRun, User,
    )
    from app.database.session import AsyncSessionLocal
    import uuid as _uuid

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"expiry-{_uuid.uuid4().hex[:6]}@x.com",
            password_hash="x",
        )
        db.add(u)
        await db.flush()
        t = Task(user_id=u.id, name="x", allowed_tools=["math"])
        db.add(t)
        await db.flush()
        run = TaskRun(
            task_id=t.id, user_id=u.id, status="waiting_approval",
            input_data={}, steps_log=[],
        )
        db.add(run)
        await db.flush()
        a = Approval(
            user_id=u.id, run_id=run.id, tool_name="shell",
            arguments={}, status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db.add(a)
        await db.commit()
        run.pending_approval_id = a.id
        await db.commit()
        aid, rid = a.id, run.id

    from app.workers.purge_worker import tick
    await tick()

    async with AsyncSessionLocal() as db:
        ap = await db.get(Approval, aid)
        rn = await db.get(TaskRun, rid)
        assert ap.status == "expired"
        assert rn.status == "failed"
        assert rn.error_code == "APPROVAL_EXPIRED"


async def test_quotas_endpoint(auth_client):
    r = await auth_client.get("/api/v1/account/quotas")
    assert r.status_code == 200
    r = await auth_client.get("/api/v1/account/quotas/limits")
    assert r.status_code == 200
