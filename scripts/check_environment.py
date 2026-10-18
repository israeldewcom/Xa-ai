"""Validates config + DB + Redis + storage at startup. Exit code 1 on error."""
import asyncio
import sys

from sqlalchemy import text

from app.config import get_settings
from app.database.session import get_engine


async def main() -> int:
    s = get_settings()
    problems: list[str] = []

    try:
        async with get_engine().begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("[ok] database")
    except Exception as exc:
        problems.append(f"database: {exc}")

    if s.redis_url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(s.redis_url, decode_responses=True)
            await r.ping()
            await r.close()
            print("[ok] redis")
        except Exception as exc:
            problems.append(f"redis: {exc}")
    else:
        print("[warn] no redis configured (in-memory rate limiter)")

    try:
        from app.services.storage import get_storage
        st = get_storage()
        st.put("__probe__", b"ok", content_type="text/plain")
        assert st.get("__probe__") == b"ok"
        st.delete("__probe__")
        print("[ok] storage")
    except Exception as exc:
        problems.append(f"storage: {exc}")

    if problems:
        for p in problems:
            print(f"[FAIL] {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
