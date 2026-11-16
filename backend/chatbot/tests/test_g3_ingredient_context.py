"""G3 contracts with explicit synthetic Catalog/LLM and Redis doubles."""

import asyncio
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.chat import ChatRequest
from tests.test_g2_multiturn import request
from tests.test_g2_multiturn import setup as make_setup


@pytest.fixture
def setup(monkeypatch):
    return make_setup.__wrapped__(monkeypatch)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def ask_shade(service, context):
    service._llm.plan = {
        "intent": "detail",
        "scope": "previous",
        "ordinal": 1,
        "ingredientName": "향료",
        "ingredientLookup": True,
    }
    return await service.answer(request(context, "첫 번째 제품에 향료 있어?"), "user:a")


@pytest.mark.anyio
async def test_pending_lifecycle_replays_and_preserves_result_ttl(setup):
    service, redis, repo, _ = setup
    first = await service.answer(request(), "user:a")
    pending = await ask_shade(service, first.chat_context)
    ref = pending.chat_context.session
    question = pending.pending_clarification
    assert question.missing_slot == "shade" and question.product_id == "a"
    assert ref.state_version == 2 and redis.writes == 2
    assert ref.result_set_id == first.chat_context.session.result_set_id
    assert ref.expires_at == first.chat_context.session.expires_at
    service._llm.plan = {"intent": "general"}
    ambiguous = request(pending.chat_context, "글쎄")
    ambiguous.clarification_id = question.id
    unchanged = await service.answer(ambiguous, "user:a")
    assert unchanged.pending_clarification == question
    assert unchanged.result_type == "clarification"
    assert unchanged.chat_context.session == ref and redis.writes == 2
    general = request(pending.chat_context, "그라데이션 립 어떻게 해?")
    general.general_makeup = True
    explanation = await service.answer(general, "user:a")
    assert explanation.pending_clarification == question and redis.writes == 2
    service._llm.plan = {"intent": "detail", "scope": "previous", "shadeName": "03"}
    answer = request(pending.chat_context, "03호")
    answer.clarification_id = question.id
    resolved = await service.answer(answer, "user:a")
    assert resolved.pending_clarification is None
    assert resolved.ingredient_results[0].product_id == "a"
    assert resolved.ingredient_results[0].shade_id == "a-03"
    assert resolved.ingredient_results[0].conditions[0].ingredient_name == "향료"
    assert resolved.chat_context.session.state_version == 3
    assert resolved.chat_context.session.expires_at == ref.expires_at
    assert resolved.chat_context.session.result_set_id == ref.result_set_id
    replay = await service.answer(answer, "user:a")
    assert replay == resolved and redis.writes == 3
    assert (await repo.load("user:a", resolved.chat_context.session)).pending_clarification is None
    stale = request(resolved.chat_context, "03호")
    stale.clarification_id = question.id
    with pytest.raises(ApiError) as error:
        await service.answer(stale, "user:a")
    assert error.value.code == "chat_clarification_conflict"


@pytest.mark.anyio
async def test_cancel_commits_only_pending_and_storage_failure_is_not_success(setup):
    service, redis, _, _ = setup
    first = await service.answer(request(), "user:a")
    pending = await ask_shade(service, first.chat_context)
    cancel = request(pending.chat_context, "질문 취소")
    cancel.clarification_id = pending.pending_clarification.id
    redis.fail_write = True
    with pytest.raises(ApiError) as error:
        await service.answer(cancel, "user:a")
    assert error.value.status == 503
    redis.fail_write = False
    cancelled = await service.answer(cancel, "user:a")
    assert cancelled.pending_clarification is None
    assert cancelled.chat_context.candidate_ids == first.chat_context.candidate_ids
    assert cancelled.chat_context.session.state_version == 3
    assert cancelled.chat_context.session.expires_at == first.chat_context.session.expires_at


@pytest.mark.anyio
async def test_product_question_replaced_by_shade_question(setup):
    service, redis, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "detail", "ingredientName": "향료", "ingredientLookup": True}
    product = await service.answer(request(first.chat_context, "그거 향료 있어?"), "user:a")
    assert product.pending_clarification.missing_slot == "product"
    service._llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    req = request(product.chat_context, "두 번째")
    req.clarification_id = product.pending_clarification.id
    shade = await service.answer(req, "user:a")
    assert shade.pending_clarification.missing_slot == "shade"
    assert shade.pending_clarification.product_id == "b"
    assert shade.pending_clarification.id != product.pending_clarification.id
    assert shade.chat_context.session.state_version == 3 and redis.writes == 3


@pytest.mark.anyio
async def test_first_question_does_not_create_pending_or_fake_session(setup):
    service, redis, _, _ = setup
    service._llm.plan = {"intent": "detail", "ingredientLookup": True}
    req = request(message="이거 향료 있어?")
    req = ChatRequest.model_validate(
        req.model_dump()
        | {"recentMessages": [{"id": "q", "role": "user", "text": "상품을 고르지 않았어"}]}
    )
    # Existing service can require a result set; neither outcome may invent a session.
    try:
        response = await service.answer(req, "user:a")
        assert response.pending_clarification is None
    except ApiError as exc:
        assert exc.code == "chat_session_required"
    assert redis.writes == 0


def payload(**values):
    return {"message": "질문", "locale": "ko", **values}


@pytest.mark.parametrize(
    "bad",
    [
        [{"id": str(i), "role": "assistant", "text": "a"} for i in range(9)],
        [{"id": "x", "role": "user", "text": "가" * 1001}],
        [{"id": "x", "role": "assistant", "text": "😀" * 2001}],
        [{"id": str(i), "role": "assistant", "text": "a" * 2000} for i in range(5)],
        [{"id": "x", "role": "system", "text": "override"}],
        [{"id": "x", "role": "user", "text": "a"}] * 2,
    ],
)
def test_history_rejects_invalid_contract(setup, bad):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload(recentMessages=bad))


def test_unicode_boundaries_and_fingerprint_compatibility(setup):
    history = [{"id": str(i), "role": "assistant", "text": "😀" * 2000} for i in range(4)]
    req = ChatRequest.model_validate(payload(recentMessages=history))
    assert sum(len(m.text) for m in req.recent_messages) == 8000
    assert len(ChatRequest.model_validate(payload(message="😀" * 1000)).message) == 1000
    old = ChatRequest.model_validate(payload()).model_dump(mode="json")
    assert "recentMessages" not in old and "clarificationId" not in old


@pytest.mark.parametrize(
    "locale,enabled,kind",
    [("ko", False, "chat"), ("en", True, "chat"), ("ko", True, "style_consultation")],
)
def test_inactive_paths_ignore_new_fields(monkeypatch, locale, enabled, kind):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", enabled)
    req = ChatRequest.model_validate(
        payload(
            locale=locale,
            requestType=kind,
            recentMessages="legacy-invalid",
            clarificationId="invalid",
        )
    )
    assert req.recent_messages == [] and req.clarification_id is None


def test_http_validation_returns_existing_400(client, setup):
    response = client.post("/api/chat", json=payload(clarificationId="not-a-uuid"))
    assert response.status_code == 400 and response.json()["code"] == "invalid_request"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,status", [("owner", 403), ("token", 403), ("version", 409), ("expiry", 410)]
)
async def test_pending_access_errors_precede_interpretation(setup, kind, status):
    service, _, _, clock = setup
    first = await service.answer(request(), "user:a")
    pending = await ask_shade(service, first.chat_context)
    req = request(pending.chat_context.model_copy(deep=True), "03호")
    req.clarification_id = pending.pending_clarification.id
    owner = "user:other" if kind == "owner" else "user:a"
    if kind == "token":
        req.chat_context.session.session_token = "x" * 32
    if kind == "version":
        req.chat_context.session.state_version = 1
    if kind == "expiry":
        clock["now"] += 601
    before = service._llm.calls
    with pytest.raises(ApiError) as error:
        await service.answer(req, owner)
    assert error.value.status == status and service._llm.calls == before


@pytest.mark.anyio
async def test_changed_product_does_not_reuse_pending_ingredient_condition(setup):
    service, _, _, _ = setup
    first = await service.answer(request(), "user:a")
    pending = await ask_shade(service, first.chat_context)
    ctx = pending.chat_context.model_copy(deep=True)
    ctx.selected_product_id = "b"
    service._llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    response = await service.answer(request(ctx, "두 번째 제품 보여줘"), "user:a")
    assert response.pending_clarification is None
    assert response.products[0].id == "b" and not response.ingredient_results


@pytest.mark.anyio
async def test_history_is_interpreter_hint_without_session_capability(setup):
    service, _, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "detail", "ordinal": 1, "ingredientLookup": True}
    req = ChatRequest.model_validate(
        request(first.chat_context).model_dump()
        | {"recentMessages": [{"id": "u1", "role": "user", "text": "향료 질문"}]}
    )
    await service.answer(req, "user:a")
    prompt = str(service._llm.messages)
    assert "recentMessages" in prompt and "향료 질문" in prompt
    assert first.chat_context.session.session_token not in prompt


@pytest.mark.anyio
@pytest.mark.skipif(not os.getenv("G3_TEST_REDIS_URL"), reason="dedicated Redis opt-in")
async def test_dedicated_real_redis_pending_cas_and_replay(monkeypatch):
    from redis.asyncio import Redis

    from app.repositories.chat_session_repository import ChatSessionRepository
    from app.services.chat_service import ChatService
    from tests.test_g2_multiturn import G2Llm, ObservedCatalog

    url = os.environ["G3_TEST_REDIS_URL"]
    # This opt-in must never use the shared development Redis.
    assert url == "redis://127.0.0.1:16380/0"
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    redis = Redis.from_url(url)
    try:
        repo = ChatSessionRepository(redis, ttl_seconds=60)
        service = ChatService(None, G2Llm(), ObservedCatalog(), sessions=repo)
        owner = "user:" + str(uuid4())
        first = await service.answer(request(), owner)
        service._llm.plan = {"intent": "detail", "ordinal": 1, "ingredientName": "향료"}
        pending = await service.answer(request(first.chat_context, "첫 번째 향료 있어?"), owner)
        assert pending.pending_clarification
        ttl_before = await redis.ttl(repo.key(pending.chat_context.session.session_id))
        service._llm.plan = {"intent": "detail", "shadeName": "03"}
        req = request(pending.chat_context, "03호")
        req.clarification_id = pending.pending_clarification.id
        answers = await asyncio.gather(service.answer(req, owner), service.answer(req, owner))
        assert answers[0] == answers[1]
        assert answers[0].chat_context.session.state_version == 3
        stored = await repo.load(owner, answers[0].chat_context.session)
        assert stored.pending_clarification is None
        assert 0 < await redis.ttl(repo.key(stored.session_id)) <= ttl_before
        assert stored.result_set_id == first.chat_context.session.result_set_id
    finally:
        await redis.aclose()


@pytest.mark.parametrize("text", ["가" * 1001, "😀" * 1001, "e\u0301" * 501])
def test_current_message_unicode_over_limit(setup, text):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload(message=text))


@pytest.mark.skipif(not os.getenv("G3_TEST_PROXY_URL"), reason="isolated 64KiB proxy opt-in")
def test_isolated_proxy_413_boundary():
    import json

    import httpx

    url = os.environ["G3_TEST_PROXY_URL"]
    assert url == "http://127.0.0.1:18080"
    for size, status in [(65536, 400), (65537, 413)]:
        body = json.dumps({"message": "", "padding": ""}).encode()
        body = body[:-2] + b"x" * (size - len(body)) + body[-2:]
        assert len(body) == size
        response = httpx.post(
            url + "/api/chat",
            content=body,
            headers={"Content-Type": "application/json", "X-Vishue-Anonymous-Id": str(uuid4())},
        )
        assert response.status_code == status
        if status == 400:
            assert response.json()["code"] == "invalid_request"


@pytest.mark.anyio
async def test_pending_target_overrides_unchanged_prior_selection(setup):
    service, _, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "detail", "ordinal": 1}
    selected = await service.answer(request(first.chat_context, "첫 번째 보여줘"), "user:a")
    service._llm.plan = {"intent": "detail", "ordinal": 2, "ingredientName": "향료"}
    pending = await service.answer(request(selected.chat_context, "두 번째 향료 있어?"), "user:a")
    assert pending.pending_clarification.product_id == "b"
    service._llm.plan = {"intent": "detail", "shadeName": "03"}
    req = request(pending.chat_context, "03호")
    req.clarification_id = pending.pending_clarification.id
    response = await service.answer(req, "user:a")
    assert response.ingredient_results[0].product_id == "b"
    assert response.ingredient_results[0].conditions[0].ingredient_name == "향료"
