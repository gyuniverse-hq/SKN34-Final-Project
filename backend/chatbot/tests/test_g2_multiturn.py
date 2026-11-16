"""G2 focused contracts: real service/router with deterministic LLM/Catalog/Redis doubles.

These tests are not a live-model, real-Redis or device evaluation of G1/G2.
"""

import asyncio
import json
import os
import time
from uuid import uuid4

import pytest
from dotenv import dotenv_values

from app.clients.catalog_client import CatalogClient
from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble, SessionCatalog


class G2Llm(PlanLlm):
    async def complete_with_tools(self, messages, tools, **kwargs):
        self.calls += 1
        return {
            "id": "g2-fixture",
            "model": "fixture-model",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "id": "g2-search",
                                "type": "function",
                                "function": {
                                    "name": "catalog_search_products",
                                    "arguments": json.dumps(
                                        {"category": "lip", "maxPriceKRW": 30000}
                                    ),
                                },
                            }
                        ]
                    },
                }
            ],
        }, 0.01


class ObservedCatalog(SessionCatalog):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def search_products(self, **kwargs):
        self.calls.append(("search", kwargs))
        return await super().search_products(**kwargs)

    async def get_product(self, pid):
        self.calls.append(("detail", pid))
        return await super().get_product(pid)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    clock = {"now": 1000}
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    return ChatService(None, G2Llm(), ObservedCatalog(), sessions=repo), redis, repo, clock


def request(context=None, message="3만원 이하 립 추천해줘", rid=None):
    return ChatRequest.model_validate(
        {
            "message": message,
            "locale": "ko",
            "requestType": "chat",
            "requestId": str(rid or uuid4()),
            **({"chatContext": context.model_dump(mode="json")} if context else {}),
        }
    )


@pytest.mark.anyio
async def test_second_product_uses_server_order_and_keeps_result_set(setup):
    service, redis, repo, _ = setup
    initial = await service.answer(request(), "user:a")
    context = initial.chat_context
    assert context.candidate_ids == ["a", "b", "c"]
    forged = context.model_copy(deep=True)
    forged.candidate_ids.reverse()
    forged.filters.max_price_krw = 1
    service._llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    result = await service.answer(request(forged, "두 번째 제품의 색상 보여줘"), "user:a")
    assert [p.id for p in result.products] == ["b"]
    assert ("detail", "b") in service._catalog.calls
    assert result.chat_context.candidate_ids == context.candidate_ids
    assert result.chat_context.filters.max_price_krw == 30000
    assert result.chat_context.session.result_set_id == context.session.result_set_id
    assert result.chat_context.session.state_version == 2
    assert result.chat_context.session.expires_at == context.session.expires_at
    stored = await repo.load("user:a", result.chat_context.session)
    assert stored.context.selected_product_id == "b" and redis.writes == 2


@pytest.mark.anyio
async def test_refine_retains_conditions_requeries_catalog_and_explicitly_clears(setup):
    service, _, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "refine", "scope": "catalog", "moisturizing": True}
    moist = await service.answer(request(first.chat_context, "촉촉한 조건도 추가해줘"), "user:a")
    service._llm.plan = {"intent": "refine", "scope": "catalog", "maxPriceKRW": 20000}
    before = len(service._catalog.calls)
    result = await service.answer(
        request(moist.chat_context, "그럼 2만원 이하로 바꾸고 촉촉한 조건은 유지해줘"), "user:a"
    )
    assert result.chat_context.filters.category == "lip"
    assert result.chat_context.filters.moisturizing is True
    assert result.chat_context.filters.max_price_krw == 20000
    assert set(result.chat_context.candidate_ids) == {"a", "b"}
    assert result.chat_context.session.result_set_id != moist.chat_context.session.result_set_id
    assert any(call[0] == "search" for call in service._catalog.calls[before:])
    assert "참고" in result.answer
    service._llm.plan = {"intent": "refine", "scope": "catalog", "clearFilters": ["moisturizing"]}
    cleared = await service.answer(request(result.chat_context, "촉촉한 조건은 빼줘"), "user:a")
    assert cleared.chat_context.filters.moisturizing is False
    assert cleared.chat_context.filters.max_price_krw == 20000


@pytest.mark.parametrize(
    "variant,status,code",
    [
        ("owner", 403, "chat_session_forbidden"),
        ("token", 403, "chat_session_forbidden"),
        ("expired", 410, "chat_session_expired"),
        ("version", 409, "chat_session_conflict"),
        ("result", 409, "chat_session_conflict"),
    ],
)
def test_http_session_errors_precede_model_catalog_and_writes(client, setup, variant, status, code):
    service, redis, _, clock = setup
    client.app.dependency_overrides[get_chat_service] = lambda: service
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    headers = {"Authorization": "Bearer ok-1"}
    initial = client.post("/api/chat", json=request().model_dump(mode="json"), headers=headers)
    assert initial.status_code == 200
    body = initial.json()
    payload = {
        "message": "두 번째 제품 보여줘",
        "locale": "ko",
        "requestType": "chat",
        "requestId": str(uuid4()),
        "chatContext": body["chatContext"],
    }
    ref = payload["chatContext"]["session"]
    if variant == "owner":
        headers = {"Authorization": "Bearer ok-2"}
    elif variant == "token":
        ref["sessionToken"] = "x" * 32
    elif variant == "expired":
        clock["now"] += 601
    else:
        service._llm.plan = {"intent": "refine", "scope": "catalog", "maxPriceKRW": 20000}
        advance = client.post(
            "/api/chat",
            json={**payload, "message": "2만원 이하로 바꿔줘", "requestId": str(uuid4())},
            headers=headers,
        )
        assert advance.status_code == 200
        current = advance.json()["chatContext"]["session"]
        if variant == "version":
            ref["resultSetId"] = current["resultSetId"]
        else:
            ref["stateVersion"] = current["stateVersion"]
    calls = (service._llm.calls, len(service._catalog.calls), redis.writes)
    result = client.post("/api/chat", json=payload, headers=headers)
    assert (result.status_code, result.json()["code"]) == (status, code)
    assert set(result.json()) == {"error", "code"}
    assert (service._llm.calls, len(service._catalog.calls), redis.writes) == calls


@pytest.mark.anyio
@pytest.mark.parametrize("same_request", [False, True])
async def test_replay_and_concurrent_version_have_one_commit(setup, same_request):
    service, redis, repo, _ = setup
    initial = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "price", "scope": "previous", "ordinal": 2}
    req = request(initial.chat_context, "두 번째 제품 가격은?")
    response = await service.answer(req, "user:a")
    calls = (service._llm.calls, len(service._catalog.calls), redis.writes)
    retry = await service.answer(req, "user:a")
    assert retry.model_dump() == response.model_dump()
    assert (service._llm.calls, len(service._catalog.calls), redis.writes) == calls
    with pytest.raises(ApiError) as error:
        await service.answer(req.model_copy(update={"message": "다른 내용"}), "user:a")
    assert error.value.code == "chat_request_conflict"
    rid = uuid4() if same_request else None
    results = await asyncio.gather(
        *[
            service.answer(request(response.chat_context, "두 번째 가격은?", rid), "user:a")
            for _ in range(2)
        ],
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, ApiError)]
    if same_request:
        assert not failures and results[0].model_dump() == results[1].model_dump()
    else:
        assert len(failures) == 1 and failures[0].code == "chat_session_conflict"
    assert redis.writes == 3
    assert (await repo.load("user:a", response.chat_context.session)).state_version == 3


@pytest.mark.anyio
async def test_general_interlude_preserves_context_and_foreign_shade_is_rejected(setup):
    service, redis, _, _ = setup
    initial = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "general"}
    general = await service.answer(request(initial.chat_context, "틴트 사용법 알려줘"), "user:a")
    assert general.chat_context == initial.chat_context
    assert general.session_status == "unchanged" and redis.writes == 1
    bad = general.chat_context.model_copy(deep=True)
    bad.shade_selections = {"a": "b-03"}
    service._llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 1}
    with pytest.raises(ApiError) as error:
        await service.answer(request(bad, "첫 번째 색상 보여줘"), "user:a")
    assert error.value.code == "invalid_chat_selection" and redis.writes == 1


@pytest.mark.anyio
@pytest.mark.skipif(not os.getenv("G2_LIVE_ENV_FILE"), reason="G2 live model/Catalog opt-in")
async def test_live_model_catalog_multiturn(monkeypatch):
    """Real model + Catalog HTTP; Redis/auth/device remain outside this smoke test."""
    env = dotenv_values(os.environ["G2_LIVE_ENV_FILE"])
    assert env.get("LLM_API_KEY") and env.get("LLM_MODEL")
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = LlmClient(
        env.get("LLM_BASE_URL") or "https://api.openai.com/v1",
        env["LLM_API_KEY"],
        env["LLM_MODEL"],
        60,
    )
    catalog = CatalogClient(os.environ["G2_LIVE_CATALOG_URL"])
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(RedisDouble()))
    owner = "user:g2-live-isolated"
    initial = await service.answer(request(message="3만원 이하 촉촉한 립 제품 추천해줘"), owner)
    context = initial.chat_context
    assert context and len(context.candidate_ids) >= 2 and context.filters.moisturizing
    detail = await service.answer(request(context, "두 번째 제품의 색상 보여줘"), owner)
    assert [p.id for p in detail.products] == [context.candidate_ids[1]]
    assert detail.chat_context.candidate_ids == context.candidate_ids
    assert detail.chat_context.session.result_set_id == context.session.result_set_id
    changed = await service.answer(
        request(detail.chat_context, "그럼 2만원 이하로 바꾸고, 촉촉한 조건은 유지해줘"), owner
    )
    assert changed.chat_context.filters.max_price_krw == 20000
    assert changed.chat_context.filters.moisturizing
    assert changed.chat_context.filters.category == context.filters.category
    assert changed.chat_context.session.result_set_id != context.session.result_set_id
    assert "참고" in changed.answer
    print(
        json.dumps(
            {
                "g1Enabled": True,
                "model": env["LLM_MODEL"],
                "candidateCount": len(context.candidate_ids),
                "ordinalMatched": True,
                "conditionsPreserved": True,
                "versions": [
                    context.session.state_version,
                    detail.chat_context.session.state_version,
                    changed.chat_context.session.state_version,
                ],
                "redis": "deterministic double",
                "auth": "service principal fixture",
            }
        )
    )
