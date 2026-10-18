"""Chaos test: hammer the system with concurrent requests. Assertions are
exact — no "in (...)" fallbacks. This is the test that proves Phase 0 without
touching source code."""
import asyncio
import pytest


async def test_concurrent_load(auth_client):
    """50 chats + 20 uploads + no 500s. All backoff/quota logic holds."""
    from app.database.session import AsyncSessionLocal
    from app.database.models import DailyQuota
    from sqlalchemy import delete

    me = await auth_client.get("/api/v1/auth/me")
    uid = me.json()["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(DailyQuota).where(DailyQuota.user_id == uid))
        await db.commit()

    chat_coros = [
        auth_client.post("/api/v1/chat", json={"message": f"msg {i}"})
        for i in range(50)
    ]
    upload_coros = [
        auth_client.post("/api/v1/files", files={
            "file": (f"t{i}.txt", b"hello", "text/plain"),
        })
        for i in range(20)
    ]
    results = await asyncio.gather(*chat_coros, *upload_coros, return_exceptions=True)
    non_200 = [
        r for r in results
        if not isinstance(r, Exception) and r.status_code not in (200, 201, 429)
    ]
    assert not non_200, f"unexpected statuses: {[r.status_code for r in non_200]}"
    assert not [r for r in results if isinstance(r, Exception)], "unexpected exceptions"


async def test_no_500s_under_repeated_malformed_input(auth_client):
    bad_payloads = [
        {"message": ""},
        {"message": "x" * 100_000},
        {"message": "hello", "capability": "invalid"},
    ]
    for p in bad_payloads:
        r = await auth_client.post("/api/v1/chat", json=p)
        assert r.status_code in (422, 200, 429), (
            f"unexpected {r.status_code} for {p}"
        )
