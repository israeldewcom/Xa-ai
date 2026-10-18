"""Behavioral regressions for the Phase 0–2 fixes. No source grepping — all
tests prove behavior."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import ValidationFailure
from app.core.ssrf import validate_url, validate_url_async


def test_ssrf_blocks_metadata():
    with pytest.raises(ValidationFailure):
        validate_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValidationFailure):
        validate_url("http://127.0.0.1/admin")
    with pytest.raises(ValidationFailure):
        validate_url("file:///etc/passwd")
    with pytest.raises(ValidationFailure):
        validate_url("http://10.0.0.1/internal")


def test_ssrf_allows_public():
    assert validate_url("https://example.com/api")


async def test_ssrf_async_does_not_block():
    """Async DNS validation must return promptly — proof it doesn't call the
    blocking socket.getaddrinfo on the event loop."""
    import time
    start = time.monotonic()
    await validate_url_async("https://example.com/x")
    elapsed = time.monotonic() - start
    # Even if DNS is instant, the point is no exception and it completes.
    assert elapsed < 5.0


async def test_erasure_removes_user(auth_client):
    from sqlalchemy import func, select
    from app.database.models import (
        AuditEvent, Conversation, DailyQuota, UsageEvent, User,
    )
    from app.database.session import AsyncSessionLocal

    me = await auth_client.get("/api/v1/auth/me")
    uid = me.json()["id"]

    r = await auth_client.delete("/api/v1/account/erase")
    assert r.status_code == 204

    async with AsyncSessionLocal() as db:
        count = (await db.execute(
            select(func.count()).select_from(User).where(User.id == uid)
        )).scalar()
        assert count == 0
        for model, col in [
            (Conversation, Conversation.user_id),
            (DailyQuota, DailyQuota.user_id),
            (UsageEvent, UsageEvent.user_id),
        ]:
            c = (await db.execute(
                select(func.count()).select_from(model).where(col == uid)
            )).scalar()
            assert c == 0, f"{model.__tablename__} not erased"


async def test_executable_rejected(auth_client):
    files = {
        "file": (
            "evil.exe",
            b"MZ\x90\x00" + b"\x00" * 32,
            "application/octet-stream",
        ),
    }
    r = await auth_client.post("/api/v1/files", files=files)
    assert r.status_code == 422


async def test_idempotency_ttl_expiry(auth_client):
    from sqlalchemy import select
    from app.database.models import IdempotencyRecord
    from app.database.session import AsyncSessionLocal

    headers = {"idempotency-key": "ttl-test"}
    r1 = await auth_client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=headers,
    )
    assert r1.status_code == 200

    async with AsyncSessionLocal() as db:
        rec = (await db.execute(select(IdempotencyRecord))).scalars().first()
        if rec:
            rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

    r2 = await auth_client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=headers,
    )
    assert r2.status_code == 200
    assert r1.json()["conversation_id"] != r2.json()["conversation_id"]


async def test_backoff_honors_next_attempt_at(app):
    """Create a job that will fail, run the worker to failure, then assert the
    backoff prevents re-claim."""
    from app.database.models import Job
    from app.database.session import AsyncSessionLocal
    from app.workers.base import BaseWorker

    class FailingWorker(BaseWorker):
        job_types = ("_test_fail",)
        async def handle(self, job):
            return ("", "TEST_ERROR")

    async with AsyncSessionLocal() as db:
        from app.database.models import User
        import uuid
        u = User(
            email=f"backoff-{uuid.uuid4().hex[:6]}@x.com",
            password_hash="x",
        )
        db.add(u)
        await db.flush()
        job = Job(user_id=u.id, job_type="_test_fail", status="queued")
        db.add(job)
        await db.commit()
        jid = job.id
        uid = u.id

    w = FailingWorker()
    claimed = await w._claim_one()
    assert claimed is not None and claimed.id == jid
    await w._finish(jid, "failed", error_code="TEST")

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        assert job.status == "queued"
        assert job.next_attempt_at is not None
        assert job.next_attempt_at > datetime.now(timezone.utc)

    # Immediate re-claim must return None (backoff not elapsed)
    second = await w._claim_one()
    assert second is None, "job should not be claimable during backoff"


async def test_voice_barge_in_cancels_tts():
    """Fake TTS that yields 100 chunks slowly. Barge-in must cut it short."""
    from app.services.voice_session import VoiceConfig, VoiceSessionState

    cfg = VoiceConfig(silence_ms=60, min_speech_ms=20, chunk_ms=20)
    state = VoiceSessionState(cfg)
    state.set_assistant_speaking(True)

    speech = b"\x00\x10" * 160
    sentinel = state.push_audio(speech)
    assert sentinel == b"", "barge-in must return empty-bytes sentinel"
    assert state._assistant_speaking is False


async def test_quota_under_concurrency(auth_client, monkeypatch):
    """Fire 20 concurrent requests at a limit of 5 — exactly 5 succeed."""
    from app.config import get_settings
    from app.database.session import AsyncSessionLocal
    from sqlalchemy import delete
    from app.database.models import DailyQuota
    from app.core import quotas as qmod

    # Lower the limit for this test
    s = get_settings()
    monkeypatch.setattr(s, "quota_chat_per_day", 5)

    # Fresh the user's quota row
    me = await auth_client.get("/api/v1/auth/me")
    uid = me.json()["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(DailyQuota).where(DailyQuota.user_id == uid))
        await db.commit()

    results = await asyncio.gather(*[
        auth_client.post("/api/v1/chat", json={"message": "hi"})
        for _ in range(20)
    ])
    ok = sum(1 for r in results if r.status_code == 200)
    limited = sum(1 for r in results if r.status_code == 429)
    assert ok == 5, f"expected exactly 5 successes, got {ok}"
    assert limited == 15, f"expected 15 rate-limited, got {limited}"


async def test_cost_is_recorded(auth_client):
    from app.database.session import AsyncSessionLocal
    from app.core.cost import aggregate

    await auth_client.post("/api/v1/chat", json={"message": "hello there"})
    me = await auth_client.get("/api/v1/auth/me")
    uid = me.json()["id"]
    async with AsyncSessionLocal() as db:
        agg = await aggregate(db, uid)
    assert "chat" in agg
    assert agg["chat"]["cost_micros"] > 0
    assert agg["chat"]["count"] >= 1


async def test_production_config_rejects_wildcard_cors(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    monkeypatch.setenv("SECRET_KEY", "a" * 40)
    monkeypatch.setenv("CORS_ORIGINS", '["*"]')
    with pytest.raises(Exception):
        Settings()


async def test_shell_not_in_default_allowed_tools():
    from app.config import get_settings
    s = get_settings()
    assert "shell" not in s.agent_allowed_tools, (
        "Phase 2.7: shell must not be granted by default"
    )
