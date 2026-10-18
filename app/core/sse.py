import json
from typing import AsyncIterator


def _format(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def sse_stream(
    source: AsyncIterator[dict], *, heartbeat_seconds: int = 15,
) -> AsyncIterator[bytes]:
    import asyncio
    import time
    last = time.monotonic()
    async for item in source:
        yield _format(item.get("event", "message"), item)
        if time.monotonic() - last > heartbeat_seconds:
            yield b": ping\n\n"
            last = time.monotonic()
    yield _format("done", {"ok": True})
