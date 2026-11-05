import json
import logging
from functools import lru_cache
from typing import Any, Protocol

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...


class NullCache:
    """Used when Redis is not configured: every read misses."""

    async def get_json(self, key: str) -> Any | None:
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        return None

    async def delete_prefix(self, prefix: str) -> None:
        return None


class RedisCache:
    """Shared across replicas. A Redis error degrades to a cache miss, never a failed request."""

    def __init__(self, client: Redis, prefix: str = "vishue:api:") -> None:
        self._client = client
        self._prefix = prefix

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(self._prefix + key)
        except Exception:
            logger.warning("cache read failed", extra={"key": key})
            return None
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self._client.set(self._prefix + key, json.dumps(value), ex=ttl_seconds)
        except Exception:
            logger.warning("cache write failed", extra={"key": key})

    async def delete_prefix(self, prefix: str) -> None:
        """Raises on Redis errors: it runs after a write, and stale data must not be served."""
        keys = [k async for k in self._client.scan_iter(match=f"{self._prefix}{prefix}*")]
        if keys:
            await self._client.delete(*keys)


@lru_cache
def get_redis() -> Redis | None:
    url = get_settings().redis_url
    return Redis.from_url(url, decode_responses=True) if url else None


def get_cache() -> Cache:
    client = get_redis()
    return RedisCache(client) if client else NullCache()


async def ping_redis() -> bool | None:
    """None when Redis is not configured (optional dependency)."""
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
