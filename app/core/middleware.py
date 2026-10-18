import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.metrics import http_request_seconds, http_requests_total


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        started = time.monotonic()
        try:
            response: Response = await call_next(request)
        finally:
            elapsed = time.monotonic() - started
            route = request.url.path
            try:
                http_request_seconds.labels(request.method, route).observe(elapsed)
            except Exception:
                pass
        response.headers["X-Request-ID"] = rid
        try:
            http_requests_total.labels(request.method, route, response.status_code).inc()
        except Exception:
            pass
        return response


class _TooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    """Pure-ASGI body cap. Also catches chunked bodies with no Content-Length."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        cl = headers.get(b"content-length")
        if cl and cl.isdigit() and int(cl) > self.max_bytes:
            return await self._reject(scope, receive, send)
        total = 0
        started = False

        async def limited_receive():
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > self.max_bytes:
                    raise _TooLarge()
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send):
        resp = JSONResponse(status_code=413, content={"error": {
            "code": "PAYLOAD_TOO_LARGE",
            "message": f"Body exceeds {self.max_bytes} bytes.",
        }})
        await resp(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response
