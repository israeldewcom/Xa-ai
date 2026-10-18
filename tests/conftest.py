import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_xa_ai.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-abcdefghijklmnopqr")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("INFERENCE_BACKEND", "stub")
os.environ.setdefault("REDIS_URL", "")

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from app.main import app as fastapi_app
from app.database.session import init_db


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def app():
    async with LifespanManager(fastapi_app):
        await init_db()
        yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    email = f"test-{os.urandom(4).hex()}@example.com"
    r = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "testpassword123",
    })
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "testpassword123",
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
