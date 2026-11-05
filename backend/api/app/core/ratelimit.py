import time
from functools import lru_cache
from typing import Protocol

from fastapi import Request

from app.core.cache import get_redis
from app.core.config import get_settings


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...


class MemoryRateLimiter:
    """Per-process fixed window. Only for local runs; replicas do not share counts."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, tuple[int, float]] = {}

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        count, start = self._hits.get(key, (0, now))
        if now - start >= self.window:
            count, start = 0, now
        if len(self._hits) > 5000:
            self._hits.clear()
        self._hits[key] = (count + 1, start)
        return count + 1 <= self.limit


class RedisRateLimiter:
    """Fixed window shared by every replica. Fails open if Redis is unreachable."""

    def __init__(self, client, name: str, limit: int, window_seconds: int = 60) -> None:
        self._client = client
        self._name = name
        self.limit = limit
        self.window = window_seconds

    async def allow(self, key: str) -> bool:
        bucket = f"vishue:api:rl:{self._name}:{key}:{int(time.time() // self.window)}"
        try:
            count = await self._client.incr(bucket)
            if count == 1:
                await self._client.expire(bucket, self.window)
        except Exception:
            return True
        return count <= self.limit


@lru_cache
def get_tutorial_rate_limiter() -> RateLimiter:
    limit = get_settings().tutorial_searches_per_minute
    client = get_redis()
    return RedisRateLimiter(client, "tutorials", limit) if client else MemoryRateLimiter(limit)


@lru_cache
def get_offer_search_rate_limiter() -> RateLimiter:
    limit = get_settings().offer_searches_per_minute
    client = get_redis()
    return RedisRateLimiter(client, "offer-search", limit) if client else MemoryRateLimiter(limit)


def client_key(request: Request) -> str:
    """Caller IP. uvicorn runs with --proxy-headers, so this is the address the gateway saw."""
    return request.client.host if request.client else "anonymous"
