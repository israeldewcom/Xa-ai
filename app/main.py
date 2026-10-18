import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin, auth, chat, conversations, devices, erasure, files, health, jobs,
    metrics as metrics_api, models as models_api, quotas, tasks, tools,
    training, voice, webhooks,
)
from app.config import get_settings
from app.core.exceptions import XAError
from app.core.logging import setup_logging
from app.core.middleware import (
    RequestContextMiddleware, RequestSizeLimitMiddleware, SecurityHeadersMiddleware,
)
from app.core.rate_limit import build_limiter
from app.database.session import get_session_factory, init_db
from app.orchestration.registry import ModelRegistry
from app.orchestration.router import RequestRouter
from app.services.device_mesh import bootstrap_server_key
from app.services.model_manager import bootstrap_registry

_s = get_settings()
setup_logging("DEBUG" if _s.debug else "INFO")
logger = logging.getLogger("xa.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    app.state.redis = None
    if _s.redis_url:
        try:
            app.state.redis = aioredis.from_url(_s.redis_url, decode_responses=True)
            await app.state.redis.ping()
            logger.info("redis_connected")
        except Exception as exc:
            logger.warning("redis_unavailable", extra={"error": str(exc)})
            app.state.redis = None

    # Bootstrap persisted X25519 so device channels survive SECRET_KEY rotation
    try:
        async with get_session_factory()() as db:
            await bootstrap_server_key(db)
    except Exception as exc:
        logger.warning("x25519_bootstrap_failed", extra={"error": str(exc)})

    app.state.login_limiter = build_limiter(
        _s.rate_limit_auth_per_minute, app.state.redis, "login", "auth",
    )
    app.state.chat_limiter = build_limiter(
        _s.rate_limit_chat_per_minute, app.state.redis, "chat", "chat",
    )
    app.state.upload_limiter = build_limiter(
        _s.rate_limit_upload_per_minute, app.state.redis, "upload", "upload",
    )
    app.state.admin_limiter = build_limiter(
        _s.rate_limit_admin_per_minute, app.state.redis, "admin", "admin",
    )
    app.state.voice_limiter = build_limiter(
        _s.rate_limit_voice_per_minute, app.state.redis, "voice", "voice",
    )
    app.state.device_limiter = build_limiter(
        _s.rate_limit_device_per_minute, app.state.redis, "device", "device",
    )
    app.state.agent_limiter = build_limiter(
        _s.rate_limit_agent_per_minute, app.state.redis, "agent", "agent",
    )

    registry = ModelRegistry()
    await bootstrap_registry(registry)
    app.state.registry = registry
    app.state.router = RequestRouter(registry)

    logger.info("startup_complete", extra={
        "backend": _s.inference_backend,
        "models": [m["name"] for m in registry.list_models()],
        "voice": _s.voice_enabled,
        "devices": _s.device_enabled,
        "automation": _s.automation_enabled,
    })
    yield
    if app.state.redis:
        await app.state.redis.close()
    logger.info("shutdown")


app = FastAPI(title=_s.app_name, version="1.3.1", lifespan=lifespan)

app.add_middleware(
    RequestSizeLimitMiddleware, max_bytes=_s.max_request_body_mb * 1024 * 1024,
)
app.add_middleware(SecurityHeadersMiddleware)
_allow_credentials = "*" not in _s.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*", "x-api-key", "idempotency-key", "x-request-id"],
    expose_headers=["x-request-id"],
)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(XAError)
async def xa_error_handler(request: Request, exc: XAError):
    rid = getattr(request.state, "request_id", None)
    headers = {}
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {
            "code": exc.code, "message": exc.message, "request_id": rid,
        }},
        headers=headers,
    )


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", None)
    logger.exception("unhandled", extra={"request_id": rid})
    return JSONResponse(
        status_code=500,
        content={"error": {
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred.",
            "request_id": rid,
        }},
    )


P = _s.api_v1_prefix
app.include_router(health.router)
app.include_router(metrics_api.router)
app.include_router(auth.router, prefix=P)
app.include_router(chat.router, prefix=P)
app.include_router(conversations.router, prefix=P)
app.include_router(models_api.router, prefix=P)
app.include_router(tools.router, prefix=P)
app.include_router(files.router, prefix=P)
app.include_router(jobs.router, prefix=P)
app.include_router(training.router, prefix=P)
app.include_router(webhooks.router, prefix=P)
app.include_router(admin.router, prefix=P)
app.include_router(voice.router, prefix=P)
app.include_router(devices.router, prefix=P)
app.include_router(tasks.router, prefix=P)
app.include_router(quotas.router, prefix=P)
app.include_router(erasure.router, prefix=P)


@app.get("/")
async def root():
    return {"name": _s.app_name, "version": "1.3.0", "docs": "/docs"}
