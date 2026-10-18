"""Outbound URL validation. Async DNS to avoid blocking the event loop."""
import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.core.exceptions import ValidationFailure

logger = logging.getLogger("xa.ssrf")
_s = get_settings()

_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript", "vbscript"}
_METADATA_HOSTS = {
    "169.254.169.254", "metadata.google.internal", "metadata",
    "100.100.100.200",
}
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
]


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _PRIVATE_NETS)


async def _resolve_host_async(host: str) -> list[str]:
    """Non-blocking DNS. Returns [] on failure."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    return list({info[4][0] for info in infos})


def _resolve_host_sync(host: str) -> list[str]:
    """Sync fallback used in non-async contexts (tests). Callers should prefer
    the async form."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return []
    return list({info[4][0] for info in infos})


async def validate_url_async(url: str, *, allow_private: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise ValidationFailure(f"Blocked URL scheme: {parsed.scheme}")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValidationFailure(f"Only http(s) URLs allowed (got {parsed.scheme})")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationFailure("URL has no host")

    if host in _METADATA_HOSTS:
        raise ValidationFailure("Metadata endpoints are blocked")

    if _s.outbound_allow_hosts and host not in _s.outbound_allow_hosts:
        raise ValidationFailure(f"Host not in allowlist: {host}")

    if not allow_private and _s.outbound_block_private_ips:
        if _is_private_ip(host):
            raise ValidationFailure(f"Private IP blocked: {host}")
        for resolved in await _resolve_host_async(host):
            if _is_private_ip(resolved):
                raise ValidationFailure(f"Host {host} resolves to private IP {resolved}")
    return url


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """Sync wrapper used by webhooks and legacy call sites. Prefer the async form
    inside async code paths."""
    parsed = urlparse(url)
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise ValidationFailure(f"Blocked URL scheme: {parsed.scheme}")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValidationFailure(f"Only http(s) URLs allowed (got {parsed.scheme})")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationFailure("URL has no host")
    if host in _METADATA_HOSTS:
        raise ValidationFailure("Metadata endpoints are blocked")
    if _s.outbound_allow_hosts and host not in _s.outbound_allow_hosts:
        raise ValidationFailure(f"Host not in allowlist: {host}")
    if not allow_private and _s.outbound_block_private_ips:
        if _is_private_ip(host):
            raise ValidationFailure(f"Private IP blocked: {host}")
        for resolved in _resolve_host_sync(host):
            if _is_private_ip(resolved):
                raise ValidationFailure(f"Host {host} resolves to private IP {resolved}")
    return url


def build_http_client(*, allow_private: bool = False) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=_s.outbound_timeout_seconds,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


async def safe_get(url: str, *, allow_private: bool = False,
                   max_bytes: int = 5 * 1024 * 1024) -> bytes:
    """Streaming GET with per-chunk size cap and async URL validation."""
    current = await validate_url_async(url, allow_private=allow_private)
    redirects = 0
    async with build_http_client(allow_private=allow_private) as client:
        while True:
            async with client.stream("GET", current) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    if redirects >= _s.outbound_max_redirects:
                        raise ValidationFailure("Too many redirects")
                    loc = r.headers.get("location", "")
                    if not loc:
                        raise ValidationFailure("Redirect with no location")
                    current = await validate_url_async(
                        str(httpx.URL(current).join(loc)),
                        allow_private=allow_private,
                    )
                    redirects += 1
                    continue
                if r.status_code >= 400:
                    r.raise_for_status()
                buf = bytearray()
                async for chunk in r.aiter_bytes(chunk_size=64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise ValidationFailure(
                            f"Response exceeds {max_bytes} bytes"
                        )
                return bytes(buf)


async def safe_post(url: str, *, body: bytes, headers: dict | None = None,
                    allow_private: bool = False,
                    max_bytes: int = 5 * 1024 * 1024) -> bytes:
    current = await validate_url_async(url, allow_private=allow_private)
    redirects = 0
    async with build_http_client(allow_private=allow_private) as client:
        while True:
            r = await client.post(current, content=body, headers=headers or {})
            if r.status_code in (301, 302, 303, 307, 308):
                if redirects >= _s.outbound_max_redirects:
                    raise ValidationFailure("Too many redirects")
                loc = r.headers.get("location", "")
                if not loc:
                    raise ValidationFailure("Redirect with no location")
                current = await validate_url_async(
                    str(httpx.URL(current).join(loc)),
                    allow_private=allow_private,
                )
                redirects += 1
                continue
            if r.status_code >= 400:
                r.raise_for_status()
            buf = bytearray()
            async for chunk in r.aiter_bytes(chunk_size=64 * 1024):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ValidationFailure(f"Response exceeds {max_bytes} bytes")
            return bytes(buf)
