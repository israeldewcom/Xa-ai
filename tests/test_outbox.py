async def test_outbox_enqueued_on_job_completion(auth_client):
    from sqlalchemy import select
    from app.database.models import OutboxEvent
    from app.database.session import AsyncSessionLocal
    from app.workers.base import BaseWorker

    r = await auth_client.post("/api/v1/jobs", json={
        "job_type": "document_processing",
    })
    jid = r.json()["id"]

    class W(BaseWorker):
        job_types = ("document_processing",)
        async def handle(self, job):
            return ("ok", "")

    await W()._finish(jid, "succeeded", output="ok")

    async with AsyncSessionLocal() as db:
        events = (await db.execute(select(OutboxEvent))).scalars().all()
        assert any(e.event == "job.completed" for e in events)


async def test_outbox_reaper_recovers_crashed_claims(app):
    """Simulate a worker that claims an event then crashes. After the lease
    expires, the reaper must re-claim it."""
    from datetime import datetime, timedelta, timezone
    from app.config import get_settings
    from app.core.outbox import claim_batch, enqueue
    from app.database.session import AsyncSessionLocal
    import uuid as _uuid

    s = get_settings()

    async with AsyncSessionLocal() as db:
        await enqueue(db, _uuid.uuid4().hex, "test.event", {"x": 1})
        await db.commit()
        claimed = await claim_batch(db, 10)
        assert len(claimed) == 1
        eid = claimed[0].id

    # Simulate: worker crashed; lease is now expired
    async with AsyncSessionLocal() as db:
        from sqlalchemy import update
        from app.database.models import OutboxEvent
        await db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == eid)
            .values(
                claimed_at=datetime.now(timezone.utc)
                - timedelta(seconds=s.webhook_outbox_lease_seconds + 10),
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        reclaimed = await claim_batch(db, 10)
        assert any(e.id == eid for e in reclaimed), (
            "reaper must re-claim events whose lease has expired"
        )
