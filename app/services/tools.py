"""Curated tool registry. Deny-by-default. Shell is NOT in AGENT_ALLOWED_TOOLS
by default — operators must opt in explicitly."""
import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import get_settings
from app.core.ssrf import safe_get, safe_post
from app.specialists.engineer import calculate

logger = logging.getLogger("xa.tools")
_s = get_settings()

_TOOL_IMPLS: dict[str, Callable[..., Awaitable[dict]]] = {}


def tool(name: str, *, description: str, schema: dict):
    def deco(fn):
        _TOOL_IMPLS[name] = fn
        _TOOL_IMPLS[name].__tool_meta__ = {  # type: ignore[attr-defined]
            "name": name, "description": description, "schema": schema,
        }
        return fn
    return deco


def tools_catalog() -> list[dict]:
    return [
        getattr(impl, "__tool_meta__", {})
        for impl in _TOOL_IMPLS.values()
        if hasattr(impl, "__tool_meta__")
    ]


def requires_approval(name: str) -> bool:
    return name in _s.agent_require_approval_for


@tool(
    "fetch_url",
    description="Fetch an HTTP(S) URL (GET) and return status + body text.",
    schema={"type": "object", "properties": {"url": {"type": "string"}},
            "required": ["url"]},
)
async def _fetch_url(url: str) -> dict:
    body = await safe_get(url, max_bytes=5 * 1024 * 1024)
    return {"status": 200, "bytes": len(body),
            "text": body.decode("utf-8", "replace")[:100_000]}


@tool(
    "http_post",
    description="POST a JSON body to an HTTP(S) URL. Requires approval by default.",
    schema={"type": "object",
            "properties": {"url": {"type": "string"}, "json": {"type": "object"}},
            "required": ["url"]},
)
async def _http_post(url: str, json: dict | None = None) -> dict:
    import json as _json
    body = _json.dumps(json or {}).encode()
    resp = await safe_post(url, body=body,
                           headers={"Content-Type": "application/json"})
    return {"status": 200, "text": resp.decode("utf-8", "replace")[:100_000]}


@tool(
    "math",
    description="Evaluate a math expression.",
    schema={"type": "object", "properties": {"expression": {"type": "string"}},
            "required": ["expression"]},
)
async def _math(expression: str) -> dict:
    return calculate(expression)


@tool(
    "llm_generate",
    description="Ask the configured LLM a question.",
    schema={"type": "object", "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"]},
)
async def _llm_generate(prompt: str, *, _router=None) -> dict:
    if _router is None:
        return {"error": "router not available in this context"}
    result = await _router.execute(prompt, "text", {})
    return {"content": result["content"]}


_SAFE_ROOT = Path(_s.training_workspace).resolve()


def _sandbox_path(path_str: str) -> Path:
    p = (_SAFE_ROOT / path_str).resolve()
    if not p.is_relative_to(_SAFE_ROOT):
        raise PermissionError("Path escapes sandbox")
    return p


@tool(
    "read_file",
    description="Read a file inside the sandboxed workspace.",
    schema={"type": "object", "properties": {"path": {"type": "string"}},
            "required": ["path"]},
)
async def _read_file(path: str) -> dict:
    p = _sandbox_path(path)
    if not p.exists():
        return {"error": "not found"}
    return {"content": p.read_text(encoding="utf-8", errors="replace")[:100_000]}


@tool(
    "write_file",
    description="Write a file inside the sandboxed workspace. Requires approval.",
    schema={"type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]},
)
async def _write_file(path: str, content: str) -> dict:
    p = _sandbox_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"bytes": len(content), "path": str(p.relative_to(_SAFE_ROOT))}


@tool(
    "sleep",
    description="Sleep N seconds (bounded).",
    schema={"type": "object", "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"]},
)
async def _sleep(seconds: float) -> dict:
    s = max(0.0, min(float(seconds), _s.agent_step_timeout_seconds))
    await asyncio.sleep(s)
    return {"slept": s}


@tool(
    "device_command",
    description="Send a command to a paired device. Requires approval.",
    schema={"type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "action": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["device_id", "action"]},
)
async def _device_command(device_id: str, action: str,
                          payload: dict | None = None,
                          *, _db=None, _user_id=None) -> dict:
    if _db is None or _user_id is None:
        return {"error": "context unavailable"}
    from app.services.device_mesh import enqueue_command
    cmd = await enqueue_command(_db, _user_id, device_id, action, payload or {})
    return {"command_id": cmd.id, "status": cmd.status}


@tool(
    "shell",
    description="Run a shell command in the sandbox. Denied unless explicitly "
                "enabled in AGENT_ALLOWED_TOOLS. Requires approval.",
    schema={"type": "object", "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"]},
)
async def _shell(cmd: str) -> dict:
    if "shell" not in _s.agent_allowed_tools:
        return {"error": "shell tool disabled"}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(_SAFE_ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(_SAFE_ROOT)},
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_s.agent_step_timeout_seconds,
        )
        return {
            "returncode": proc.returncode,
            "stdout": (stdout or b"").decode("utf-8", "replace")[:50_000],
            "stderr": (stderr or b"").decode("utf-8", "replace")[:50_000],
        }
    except asyncio.TimeoutError:
        return {"error": "timeout"}


async def execute_tool(
    name: str, arguments: dict[str, Any],
    *, context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"unknown tool: {name}"}
    if name not in _s.agent_allowed_tools:
        return {"error": f"tool disabled: {name}"}
    ctx = context or {}
    # Strip model-supplied private args so the LLM cannot inject _db etc.
    kwargs = {k: v for k, v in (arguments or {}).items() if not k.startswith("_")}
    params = inspect.signature(impl).parameters
    for k in ("_db", "_user_id", "_router"):
        if k in ctx and k in params:
            kwargs[k] = ctx[k]
    try:
        result = await asyncio.wait_for(
            impl(**kwargs), timeout=_s.agent_step_timeout_seconds,
        )
        return result or {}
    except asyncio.TimeoutError:
        return {"error": "tool timeout"}
    except TypeError as exc:
        return {"error": f"bad arguments: {exc}"}
    except Exception as exc:
        logger.warning("tool_error", extra={"tool": name, "error": str(exc)})
        return {"error": str(exc)}
