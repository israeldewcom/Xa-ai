import logging
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Protocol

from app.config import get_settings
from app.core.exceptions import RateLimited
from app.core.metrics import rate_limit_hits_total

logger = logging.getLogger("xa.rate_limit")
_s = get_settings()


class RateLimitExceeded(RateLimited):
    def __init__(self, retry_after: int = 60, route: str = ""):
        super().__init__("Rate limit exceeded.", retry_after=retry_after)
        if route:
            try:
                rate_limit_hits_total.labels(route=route).inc()
            except Exception:
                pass


class RateLimiter(Protocol):
    async def check(self, key: str) -> None: ...


class InMemoryRateLimiter:
    def __init__(self, per_minute: int, route: str = ""):
        self.per_minute = per_minute
        self.route = route
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    async def check(self, key: str) -> None:
        now = time.time()
        cutoff = now - 60
        with self._lock:
            bucket = [t for t in self._buckets[key] if t >= cutoff]
            if len(bucket) >= self.per_minute:
                retry_after = max(1, int(60 - (now - bucket[0])))
                raise RateLimitExceeded(retry_after, self.route)
            bucket.append(now)
            self._buckets[key] = bucket


class RedisRateLimiter:
    def __init__(self, client, per_minute: int, prefix: str = "rl", route: str = ""):
        self.client = client
        self.per_minute = per_minute
        self.prefix = prefix
        self.route = route

    async def check(self, key: str) -> None:
        rkey = f"{self.prefix}:{key}"
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = self.client.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - 60)
        pipe.zadd(rkey, {member: now})
        pipe.zcard(rkey)
        pipe.expire(rkey, 120)
        _, _, count, _ = await pipe.execute()
        if count > self.per_minute:
            await self.client.zrem(rkey, member)
            raise RateLimitExceeded(60, self.route)


def build_limiter(
    per_minute: int, redis_client=None, prefix: str = "rl", route: str = "",
) -> RateLimiter:
    if redis_client is not None:
        return RedisRateLimiter(redis_client, per_minute, prefix, route)
    if _s.environment == "production":
        logger.warning(
            "in_memory_rate_limiter_in_production",
            extra={"note": "Multi-worker multiplies limits by worker count."},
        )
    return InMemoryRateLimiter(per_minute, route)
