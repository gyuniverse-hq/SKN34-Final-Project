import time
from functools import lru_cache
from typing import Protocol

from redis.asyncio import Redis

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
        self._hits[key] = (count + 1, start)
        return count + 1 <= self.limit


class RedisRateLimiter:
    """Fixed window shared by every replica. Fails open if Redis is unreachable."""

    def __init__(self, client: Redis, limit: int, window_seconds: int = 60) -> None:
        self._client = client
        self.limit = limit
        self.window = window_seconds

    async def allow(self, key: str) -> bool:
        bucket = f"vishue:chat:rl:{key}:{int(time.time() // self.window)}"
        try:
            count = await self._client.incr(bucket)
            if count == 1:
                await self._client.expire(bucket, self.window)
        except Exception:
            return True
        return count <= self.limit


@lru_cache
def get_redis() -> Redis | None:
    url = get_settings().redis_url
    return Redis.from_url(url, decode_responses=True) if url else None


@lru_cache
def get_rate_limiter() -> RateLimiter:
    limit = get_settings().chat_requests_per_minute
    client = get_redis()
    return RedisRateLimiter(client, limit) if client else MemoryRateLimiter(limit)


async def ping_redis() -> bool | None:
    client = get_redis()
    if client is None:
        return None
    try:
        return bool(await client.ping())
    except Exception:
        return False


async def close_redis() -> None:
    if get_redis.cache_info().currsize and (client := get_redis()):
        await client.aclose()
