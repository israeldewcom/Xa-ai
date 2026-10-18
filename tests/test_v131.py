"""Regression tests for the v1.3.1 fixes. Run against PostgreSQL in CI."""
import asyncio
import time

import pytest


# ---- 1. Redis rate limiter -------------------------------------------------
async def test_redis_limiter_blocks():
    import fakeredis.aioredis
    from app.core.rate_limit import RateLimitExceeded, RedisRateLimiter

    lim = RedisRateLimiter(fakeredis.aioredis.FakeRedis(), 3, route="t")
    for _ in range(3):
        await lim.check("k")
    with pytest.raises(RateLimitExceeded):
        await lim.check("k")


async def test_in_memory_limiter_blocks():
    from app.core.rate_limit import InMemoryRateLimiter, RateLimitExceeded

    lim = InMemoryRateLimiter(2)
    await lim.check("k")
    await lim.check("k")
    with pytest.raises(RateLimitExceeded):
        await lim.check("k")


# ---- 2. Tool context -------------------------------------------------------
async def test_tool_private_args_stripped():
    from app.services.tools import execute_tool

    r = await execute_tool("math", {"expression": "2+2", "_db": "evil"}, context={})
    assert r.get("result") == "4"


async def test_tool_bad_arguments_reported_not_raised():
    from app.services.tools import execute_tool

    r = await execute_tool("math", {"nonsense": 1}, context={})
    assert "error" in r


def test_sandbox_rejects_escape():
    from app.services.tools import _sandbox_path

    with pytest.raises(PermissionError):
        _sandbox_path("../../etc/passwd")


def test_local_storage_rejects_sibling_prefix(tmp_path):
    """`/data/store-evil` must not pass a naive startswith check on `/data/store`."""
    from app.services.storage import LocalStorage

    root = tmp_path / "store"
    (tmp_path / "store-evil").mkdir()
    st = LocalStorage(str(root))
    with pytest.raises(ValueError):
        st._p("../store-evil/x")


# ---- 3. Devices ------------------------------------------------------------
async def _register_device(auth_client, name="phone"):
    from app.core.crypto import generate_ed25519, generate_x25519

    ed = generate_ed25519()
    _, x_pub = generate_x25519()
    r = await auth_client.post("/api/v1/devices", json={
        "name": name, "kind": "phone", "capabilities": ["notify"],
        "ed25519_pub": ed.public_b64, "x25519_pub": x_pub,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"], ed


def _sign(dev_id, ed, method, path):
    from app.core.crypto import b64e

    ts = int(time.time())
    msg = f"{dev_id}.{ts}.{method}.{path}".encode()
    return {
        "x-device-id": dev_id, "x-device-ts": str(ts),
        "x-device-sig": b64e(ed.sign(msg)),
    }


async def test_pairing_code_is_eight_digits_and_bound_to_device(auth_client):
    dev_a, _ = await _register_device(auth_client, "a")
    dev_b, _ = await _register_device(auth_client, "b")
    r = await auth_client.post(f"/api/v1/devices/{dev_a}/pair/start")
    code = r.json()["code"]
    assert len(code) == 8 and code.isdigit()
    # Code for device A must not pair device B.
    r = await auth_client.post(
        f"/api/v1/devices/{dev_b}/pair/complete", json={"code": code},
    )
    assert r.status_code == 422 or r.status_code == 400
    r = await auth_client.post(
        f"/api/v1/devices/{dev_a}/pair/complete", json={"code": code},
    )
    assert r.status_code == 200


async def test_device_poll_and_result_flow(auth_client):
    dev_id, ed = await _register_device(auth_client)
    code = (await auth_client.post(f"/api/v1/devices/{dev_id}/pair/start")).json()["code"]
    await auth_client.post(f"/api/v1/devices/{dev_id}/pair/complete", json={"code": code})

    r = await auth_client.post(
        f"/api/v1/devices/{dev_id}/commands",
        json={"action": "notify", "payload": {"text": "hi"}},
    )
    assert r.status_code == 201, r.text
    cmd_id = r.json()["id"]

    # Unsigned / badly signed polls are rejected.
    r = await auth_client.get("/api/v1/devices/me/poll", headers={
        "x-device-id": dev_id, "x-device-ts": str(int(time.time())),
        "x-device-sig": "AAAA",
    })
    assert r.status_code in (401, 403)

    r = await auth_client.get(
        "/api/v1/devices/me/poll", headers=_sign(dev_id, ed, "GET", "/api/v1/devices/me/poll"),
    )
    assert r.status_code == 200, r.text
    cmds = r.json()["commands"]
    assert [c["id"] for c in cmds] == [cmd_id]

    path = f"/api/v1/devices/me/commands/{cmd_id}/result"
    r = await auth_client.post(
        path, json={"result_enc": "opaque"}, headers=_sign(dev_id, ed, "POST", path),
    )
    assert r.status_code == 204, r.text
    # Second result for the same command is refused (no longer "delivered").
    r = await auth_client.post(
        path, json={"result_enc": "again"}, headers=_sign(dev_id, ed, "POST", path),
    )
    assert r.status_code in (400, 422)


# ---- 4. Voice --------------------------------------------------------------
def test_pcm_to_wav_roundtrip():
    import io
    import wave

    from app.core.audio_codec import pcm_to_wav

    pcm = b"\x00\x01" * 160
    with wave.open(io.BytesIO(pcm_to_wav(pcm, 16000)), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.readframes(w.getnframes()) == pcm


# ---- 10. Quotas ------------------------------------------------------------
async def test_quota_atomic_under_concurrency(auth_client):
    from app.core.exceptions import RateLimited
    from app.core.quotas import check_and_increment
    from app.database.session import AsyncSessionLocal

    uid = (await auth_client.get("/api/v1/auth/me")).json()["id"]

    async def one():
        async with AsyncSessionLocal() as db:
            try:
                await check_and_increment(db, uid, "t_conc", 1, 5)
                return True
            except RateLimited:
                return False

    results = await asyncio.gather(*[one() for _ in range(20)])
    assert sum(results) == 5


# ---- 11. Router ------------------------------------------------------------
@pytest.mark.parametrize("msg,cap", [
    ("write a python function", "coding"),
    ("what is 2+2", "math"),
    ("I have symptoms of a cold", "health"),
    ("tell me about the stack of plates in my kitchen", "text"),
    ("what is the capital of France", "text"),
])
def test_router_classify(msg, cap):
    from app.orchestration.registry import ModelRegistry
    from app.orchestration.router import RequestRouter

    assert RequestRouter(ModelRegistry()).classify(msg, "auto") == cap


# ---- Middleware / uploads --------------------------------------------------
async def test_oversized_body_rejected(client):
    from app.config import get_settings

    big = b"x" * (get_settings().max_request_body_mb * 1024 * 1024 + 1)
    r = await client.post("/api/v1/auth/login", content=big,
                          headers={"content-type": "application/json"})
    assert r.status_code == 413


async def test_upload_roundtrip_and_isolation(auth_client, app):
    from httpx import ASGITransport, AsyncClient

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = await auth_client.post(
        "/api/v1/files", files={"file": ("a.png", png, "image/png")},
    )
    if r.status_code == 422:
        pytest.skip("image/png not in allowed_mime_types for this config")
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert (await auth_client.get(f"/api/v1/files/{fid}/download")).content == png

    # A different user must not see it (404, not 403: don't confirm existence).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        import os
        email = f"o-{os.urandom(4).hex()}@example.com"
        await other.post("/api/v1/auth/register",
                         json={"email": email, "password": "testpassword123"})
        tok = (await other.post("/api/v1/auth/login",
                                json={"email": email, "password": "testpassword123"})).json()["access_token"]
        r = await other.get(f"/api/v1/files/{fid}",
                            headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 404
