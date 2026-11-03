"""Loopback-only integration worker: REAL Redis, explicit Catalog/LLM/Auth fixtures."""

import asyncio
import json
import os
import re
import time
from uuid import UUID

import uvicorn
from fastapi import Request
from redis.exceptions import WatchError

from app.clients.catalog_client import get_catalog_client
from app.clients.llm_client import get_llm_client
from app.core import auth
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter, get_redis
from app.main import create_app
from app.repositories.chat_session_repository import ChatSessionRepository, get_chat_sessions
from tests.test_chat_sessions import SessionCatalog


class FixtureLlm:
    configured = True

    async def complete(self, messages):
        message = json.loads(messages[-1]["content"])["message"]
        plans = {
            "립 상품 검색": {"intent": "search", "category": "lip", "maxPriceKRW": 20000},
            "베이스 상품 검색": {"intent": "search", "category": "base"},
            "두 번째 상품 가격은?": {"intent": "price", "ordinal": 2},
            "선택 상품 성분": {
                "intent": "detail",
                "ingredientLookup": True,
                "ingredientName": "향료",
            },
            "선택 상품 가격": {"intent": "price"},
        }
        if message not in plans:
            raise ValueError("Only documented fixture prompts are supported")
        await asyncio.sleep(0.02)
        return json.dumps(plans[message])


class FixtureVerifier:
    async def verify(self, token):
        if token not in {"fixture-user-A", "fixture-user-B"}:
            return None
        return {"sub": token, "role": "authenticated"}


class NamespacedSessions(ChatSessionRepository):
    """Only key names differ; ownership, CAS, serialization and TTL are production code."""

    def __init__(self, client, prefix, ttl):
        super().__init__(client, ttl)
        self.prefix = prefix

    def key(self, session_id):
        return self.prefix + super().key(session_id)

    def request_key(self, owner, request_id):
        return self.prefix + super().request_key(owner, request_id)


class GatedRedis:
    def __init__(self, client, gate, prefix):
        self.client, self.gate, self.prefix = client, gate, prefix

    def __getattr__(self, name):
        return getattr(self.client, name)

    def pipeline(self, transaction=True):
        return GatedPipeline(self.client.pipeline(transaction=transaction), self)


class GatedPipeline:
    def __init__(self, pipeline, redis):
        self.pipeline, self.redis = pipeline, redis

    async def __aenter__(self):
        await self.pipeline.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.pipeline.__aexit__(*args)

    def __getattr__(self, name):
        return getattr(self.pipeline, name)

    async def execute(self):
        # Both processes have WATCHed and read the same version before either REAL EXEC.
        key = self.redis.prefix + "gate:" + self.redis.gate
        await self.redis.client.incr(key)
        await self.redis.client.expire(key, 15)
        deadline = time.monotonic() + 4
        while int(await self.redis.client.get(key) or 0) < 2:
            if time.monotonic() >= deadline:
                raise TimeoutError("Integration gate timed out")
            await asyncio.sleep(0.01)
        try:
            return await self.pipeline.execute()
        except WatchError:
            await self.redis.client.incr(self.redis.prefix + "watch-errors")
            raise


def fixture_app():
    run_id = os.environ["P03C_RUN_ID"]
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Invalid isolated integration run ID")
    prefix = f"vishue:p03c:{run_id}:"
    client = get_redis()
    if client is None:
        raise ValueError("Real Redis is required; no memory fallback")
    app = create_app()
    app.dependency_overrides[get_catalog_client] = SessionCatalog
    app.dependency_overrides[get_llm_client] = FixtureLlm
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(1000)
    auth.get_verifier = lambda: FixtureVerifier()

    def sessions(request: Request):
        gate = request.headers.get("x-p03c-cas")
        if gate:
            gate = UUID(gate).hex
        redis = GatedRedis(client, gate, prefix) if gate else client
        return NamespacedSessions(redis, prefix, int(os.environ["CHAT_SESSION_TTL_SECONDS"]))

    app.dependency_overrides[get_chat_sessions] = sessions

    @app.get("/__p03c/ready")
    def ready():
        return {"pid": os.getpid(), "worker": os.environ["P03C_WORKER"], "runId": run_id}

    return app


if __name__ == "__main__":
    uvicorn.run(
        fixture_app(),
        host="127.0.0.1",
        port=int(os.environ["P03C_HTTP_PORT"]),
        access_log=False,
        log_level="warning",
    )
