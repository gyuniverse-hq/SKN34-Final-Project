"""Deterministic Redis WATCH/MULTI double; not proof of a real Redis deployment."""

import asyncio
import json
import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from redis.exceptions import RedisError, WatchError

from app.clients.catalog_client import IngredientLookupError
from app.core.errors import ApiError, UpstreamError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import CatalogIngredients
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from tests.test_beauty_consultation import Catalog, PlanLlm
from tests.test_ingredient_consultation import evidence


class RedisDouble:
    def __init__(self):
        self.rows, self.versions = {}, {}
        self.fail_read = self.fail_write = False
        self.fail_after_write = False
        self.writes = 0

    async def get(self, key):
        if self.fail_read:
            raise RedisError("synthetic read failure")
        entry = self.rows.get(key)
        return entry[0] if entry and entry[1] > time.time() else None

    def pipeline(self, transaction=True):
        assert transaction
        return Pipeline(self)


class Pipeline:
    def __init__(self, redis):
        self.redis, self.watched, self.commands = redis, {}, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def watch(self, *keys):
        if self.redis.fail_read:
            raise RedisError("synthetic watch failure")
        self.watched = {key: self.redis.versions.get(key, 0) for key in keys}

    async def get(self, key):
        await asyncio.sleep(0)
        return await self.redis.get(key)

    def multi(self):
        pass

    def set(self, key, value, ex):
        self.commands.append((key, value, ex))

    async def execute(self):
        if self.redis.fail_write:
            raise RedisError("synthetic write failure")
        if any(self.redis.versions.get(k, 0) != v for k, v in self.watched.items()):
            raise WatchError("synthetic CAS conflict")
        for key, value, ttl in self.commands:
            self.redis.rows[key] = (value, time.time() + ttl)
            self.redis.versions[key] = self.redis.versions.get(key, 0) + 1
        self.redis.writes += 1
        if self.redis.fail_after_write:
            raise RedisError("synthetic lost commit acknowledgement")
        return [True, True]


class SessionCatalog(Catalog):
    def __init__(self):
        super().__init__()
        self.ingredient_calls = []
        for p in self.products:
            p.shades = [p.shades[0].model_copy(update={"id": f"{p.id}-03", "name": "03"})]

    async def get_ingredients(self, pid, shade, *, ingredient_name=None, operator="includes"):
        self.ingredient_calls.append((pid, shade))
        return CatalogIngredients.model_validate(
            evidence(
                pid=pid,
                shade=shade,
                name=ingredient_name,
                operator=operator,
            )
        )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def setup(monkeypatch):
    clock = {"now": 1000}
    monkeypatch.setattr(time, "time", lambda: clock["now"])
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    catalog = SessionCatalog()
    return ChatService(None, llm, catalog, sessions=repo), redis, repo, clock


def request(context=None, *, message="상품 추천", rid=None, screen=None):
    return ChatRequest(
        message=message,
        locale="ko",
        request_type="beauty_consultation",
        chat_context=context,
        request_id=rid or uuid4(),
        screen_context=screen,
    )


async def first(setup):
    service = setup[0]
    return await service.answer(request(), "guest:one")


@pytest.mark.anyio
async def test_search_second_product_price_filters_and_authoritative_order(setup):
    service, redis, repo, _ = setup
    initial = await first(setup)
    ctx = initial.chat_context
    assert ctx.candidate_ids == ["a", "b"] and initial.session_status == "stored"
    tampered = ctx.model_copy(deep=True)
    tampered.candidate_ids.reverse()
    tampered.filters.max_price_krw = 1
    service._llm.plan = {"intent": "price", "ordinal": 2}
    result = await service.answer(request(tampered, message="두 번째 가격"), "guest:one")
    assert result.products[0].id == "b" and "19,000" in result.answer
    assert result.chat_context.filters.max_price_krw == 20000
    assert result.chat_context.session.result_set_id == ctx.session.result_set_id
    assert result.chat_context.session.state_version == 2
    assert result.supervisor.intent.slots.ordinal == 2
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 16000}
    refined = await service.answer(request(result.chat_context), "guest:one")
    assert refined.chat_context.candidate_ids == ["a"]
    assert refined.chat_context.session.result_set_id != ctx.session.result_set_id
    stored = await repo.load("guest:one", refined.chat_context.session)
    assert stored.owner_kind == "guest" and stored.context.session is None
    assert redis.writes == 3


@pytest.mark.anyio
async def test_selection_ingredients_revalidated_and_only_evidence_references_stored(setup):
    service, _, repo, _ = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.selected_product_id = "b"
    ctx.shade_selections = {"b": "b-03"}
    service._llm.plan = {"intent": "detail", "ingredientLookup": True, "ingredientName": "향료"}
    response = await service.answer(request(ctx), "guest:one")
    assert response.ingredient_results[0].product_id == "b"
    state = await repo.load("guest:one", response.chat_context.session)
    assert state.context.shade_selections == {"b": "b-03"}
    assert state.evidence_refs[0]["sourceVersion"] == "synthetic-v1"
    assert "message" not in state.model_dump()  # No user transcript retained.
    service._catalog.products[1].shades = []
    with pytest.raises(ApiError) as exc:
        await service.answer(request(response.chat_context), "guest:one")
    assert exc.value.code == "chat_catalog_changed"


@pytest.mark.anyio
async def test_foreign_shade_rejected_before_tool_and_state_unchanged(setup):
    service, redis, repo, _ = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.shade_selections = {"a": "b-03"}
    service._llm.plan = {"intent": "price", "ordinal": 1}
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "invalid_chat_selection" and redis.writes == 1
    assert (await repo.load("guest:one", ctx.session)).state_version == 1


@pytest.mark.anyio
@pytest.mark.parametrize("owner", ["guest:two", "user:one"])
async def test_other_principal_cannot_read_session(setup, owner):
    service = setup[0]
    ctx = (await first(setup)).chat_context
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), owner)
    assert exc.value.code == "chat_session_forbidden"


@pytest.mark.anyio
async def test_same_claimed_guest_identity_still_requires_server_capability(setup):
    service = setup[0]
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.session.session_token = "forged" * 8
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.status == 403


@pytest.mark.anyio
async def test_expiry_old_result_and_missing_server_reference(setup):
    service, _, _, clock = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "detail", "ordinal": 2}
    no_ref = ctx.model_copy(deep=True, update={"session": None})
    with pytest.raises(ApiError, match="server result set"):
        await service.answer(request(no_ref), "guest:one")
    clock["now"] += 601
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_expired"


@pytest.mark.anyio
async def test_old_version_and_result_set_rejected(setup):
    service = setup[0]
    old = (await first(setup)).chat_context
    newer = await service.answer(request(old), "guest:one")
    assert newer.chat_context.session.result_set_id != old.session.result_set_id
    service._llm.plan = {"intent": "detail", "ordinal": 2}
    with pytest.raises(ApiError) as exc:
        await service.answer(request(old), "guest:one")
    assert exc.value.code == "chat_session_conflict"


@pytest.mark.anyio
async def test_retry_is_cached_without_llm_or_duplicate_state_change(setup):
    service, redis, _, _ = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}
    req = request(ctx, message="두 번째 가격")
    response = await service.answer(req, "guest:one")
    retry = await service.answer(req, "guest:one")
    assert retry.model_dump(mode="json") == response.model_dump(mode="json")
    assert service._llm.calls == 2 and redis.writes == 2
    changed = req.model_copy(update={"message": "different"})
    with pytest.raises(ApiError) as exc:
        await service.answer(changed, "guest:one")
    assert exc.value.code == "chat_request_conflict"


@pytest.mark.anyio
async def test_concurrent_new_requests_have_exactly_one_cas_winner(setup):
    service, redis, repo, _ = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}
    results = await asyncio.gather(
        *[service.answer(request(ctx), "guest:one") for _ in range(2)], return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, ApiError)]
    assert len(failures) == 1 and failures[0].code == "chat_session_conflict"
    assert redis.writes == 2 and (await repo.load("guest:one", ctx.session)).state_version == 2


@pytest.mark.anyio
async def test_redis_failures_do_not_claim_persistence_or_remove_prior_state(setup):
    service, redis, repo, _ = setup
    ctx = (await first(setup)).chat_context
    redis.fail_write = True
    service._llm.plan = {"intent": "price", "ordinal": 2}
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_unavailable"
    assert (await repo.load("guest:one", ctx.session)).state_version == 1
    service._llm.plan = {"intent": "search", "category": "lip"}
    independent = await service.answer(request(), "guest:one")
    assert independent.session_status == "unavailable" and independent.chat_context.session is None
    assert independent.supervisor.result.status == "partial"
    assert independent.products and "저장하지 못했습니다" in independent.answer


@pytest.mark.anyio
async def test_failed_tool_does_not_delete_last_success(setup):
    service, redis, repo, _ = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}

    async def broken(pid):
        raise UpstreamError("synthetic catalog outage")

    service._catalog.get_product = broken
    with pytest.raises(ApiError):
        await service.answer(request(ctx), "guest:one")
    assert (await repo.load("guest:one", ctx.session)).context.candidate_ids == ["a", "b"]
    assert redis.writes == 1


@pytest.mark.anyio
async def test_ttl_is_absolute_for_detail_and_configurable(setup):
    service, _, repo, clock = setup
    repo.ttl_seconds = 20
    ctx = (await first(setup)).chat_context
    clock["now"] += 10
    repo.ttl_seconds = 40  # Replica configuration changes must not extend existing results.
    service._llm.plan = {"intent": "price", "ordinal": 1}
    detail = await service.answer(request(ctx), "guest:one")
    assert detail.chat_context.session.expires_at == 1020
    assert detail.chat_context.issued_at == 1000
    for ttl in [0, 601]:
        with pytest.raises(ApiError):
            ChatSessionRepository(RedisDouble(), ttl)


def test_http_keeps_legacy_fields_and_uses_authenticated_router_principal(client, setup):
    service = setup[0]
    client.app.dependency_overrides[get_chat_service] = lambda: service
    response = client.post(
        "/api/chat",
        json=request().model_dump(mode="json"),
        headers={
            "X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert {"answer", "products", "chatContext", "sessionStatus"} <= body.keys()
    assert body["chatContext"]["session"]["stateVersion"] == 1
    assert "supervisor" not in body and "owner" not in json.dumps(body)


@pytest.mark.anyio
async def test_concurrent_same_request_commits_once_and_returns_same_response(setup):
    service, redis, _, _ = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}
    req = request(ctx)
    responses = await asyncio.gather(
        service.answer(req, "guest:one"), service.answer(req, "guest:one")
    )
    assert responses[0].model_dump(mode="json") == responses[1].model_dump(mode="json")
    assert redis.writes == 2


@pytest.mark.anyio
async def test_no_redis_new_search_degrades_but_followup_fails_closed(setup):
    service = setup[0]
    service._sessions = ChatSessionRepository(None)
    initial = await service.answer(request(), "guest:one")
    assert initial.session_status == "unavailable" and initial.products
    service._llm.plan = {"intent": "price", "ordinal": 2}
    with pytest.raises(ApiError) as exc:
        await service.answer(request(initial.chat_context), "guest:one")
    assert exc.value.code == "chat_session_unavailable"


@pytest.mark.anyio
async def test_redis_read_failure_blocks_followup_and_allows_new_search(setup):
    service, redis, _, _ = setup
    ctx = (await first(setup)).chat_context
    redis.fail_read = True
    service._llm.plan = {"intent": "price", "ordinal": 2}
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_unavailable"
    service._llm.plan = {"intent": "search", "category": "lip"}
    response = await service.answer(request(ctx), "guest:one")
    assert response.session_status == "unavailable" and response.products


@pytest.mark.anyio
async def test_fresh_search_recovers_after_prior_catalog_product_removed(setup):
    service = setup[0]
    ctx = (await first(setup)).chat_context
    service._catalog.products = [p for p in service._catalog.products if p.id != "a"]
    result = await service.answer(request(ctx), "guest:one")
    assert result.chat_context.candidate_ids == ["b"]
    assert result.chat_context.session.result_set_id != ctx.session.result_set_id


@pytest.mark.anyio
async def test_ingredient_api_failure_is_not_persisted_and_next_query_revalidates(setup):
    service, redis, repo, _ = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.selected_product_id = "b"
    ctx.shade_selections = {"b": "b-03"}
    original = service._catalog.get_ingredients

    async def unavailable(*args, **kwargs):
        raise IngredientLookupError("source_unavailable")

    service._catalog.get_ingredients = unavailable
    service._llm.plan = {"intent": "detail", "ingredientLookup": True, "ingredientName": "향료"}
    error = await service.answer(request(ctx), "guest:one")
    assert error.ingredient_results[0].verdict == "ERROR" and error.session_status == "unchanged"
    # Public errors retain the queried shade and remain valid ChatResponse payloads.
    from app.schemas.chat import ChatResponse

    ChatResponse.model_validate(error.model_dump(mode="json"))
    assert (await repo.load("guest:one", ctx.session)).state_version == 1
    assert redis.writes == 1
    service._catalog.get_ingredients = original
    ok = await service.answer(request(error.chat_context), "guest:one")
    assert ok.ingredient_results[0].verdict == "MATCH" and redis.writes == 2

    async def changed(*args, **kwargs):
        value = await original(*args, **kwargs)
        value.source_version = "synthetic-v2"
        return value

    service._catalog.get_ingredients = changed
    latest = await service.answer(request(ok.chat_context), "guest:one")
    assert latest.ingredient_results[0].source_version == "synthetic-v2"
    assert (await repo.load("guest:one", latest.chat_context.session)).evidence_refs[0][
        "sourceVersion"
    ] == "synthetic-v2"


def test_http_authenticated_owner_and_guest_are_separate(client, setup):
    service, redis, _, _ = setup
    client.app.dependency_overrides[get_chat_service] = lambda: service
    response = client.post(
        "/api/chat",
        json=request().model_dump(mode="json"),
        headers={"Authorization": "Bearer ok-member"},
    )
    assert response.status_code == 200
    snapshots = [json.loads(row[0]) for key, row in redis.rows.items() if ":session:" in key]
    assert snapshots[0]["owner"] == "user:user-ok-member"
    assert snapshots[0]["ownerKind"] == "user"


@pytest.mark.anyio
async def test_bootstrap_retry_never_discloses_capability_or_creates_another_state(setup):
    service, redis, _, _ = setup
    req = request()
    await service.answer(req, "guest:one")
    with pytest.raises(ApiError) as exc:
        await service.answer(req, "guest:one")
    assert exc.value.code == "chat_request_conflict"
    assert redis.writes == 1 and service._llm.calls == 1


@pytest.mark.anyio
async def test_legacy_bootstrap_retry_also_cannot_create_duplicate_state(setup):
    service, redis, _, _ = setup
    req = request().model_copy(update={"request_id": None})
    await service.answer(req, "guest:one")
    with pytest.raises(ApiError) as exc:
        await service.answer(req, "guest:one")
    assert exc.value.code == "chat_request_conflict"
    assert redis.writes == 1 and service._llm.calls == 1


@pytest.mark.anyio
async def test_existing_app_without_request_id_retries_session_snapshot_idempotently(setup):
    service, redis, _, _ = setup
    initial = request().model_copy(update={"request_id": None})
    ctx = (await service.answer(initial, "guest:one")).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}
    req = request(ctx).model_copy(update={"request_id": None})
    result = await service.answer(req, "guest:one")
    retry = await service.answer(req, "guest:one")
    assert retry.model_dump(mode="json") == result.model_dump(mode="json")
    assert redis.writes == 2 and service._llm.calls == 2


def test_real_http_dependency_factory_preserves_existing_app_json(client, setup):
    from app.clients.catalog_client import get_catalog_client
    from app.clients.llm_client import get_llm_client
    from app.repositories.chat_session_repository import get_chat_sessions

    service, _, repo, _ = setup
    client.app.dependency_overrides.pop(get_chat_service)
    client.app.dependency_overrides[get_catalog_client] = lambda: service._catalog
    client.app.dependency_overrides[get_llm_client] = lambda: service._llm
    client.app.dependency_overrides[get_chat_sessions] = lambda: repo
    headers = {"X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk"}
    first_body = request().model_dump(mode="json")
    first_body.pop("requestId")
    initial = client.post("/api/chat", json=first_body, headers=headers)
    assert initial.status_code == 200
    context = initial.json()["chatContext"]
    service._llm.plan = {"intent": "price", "ordinal": 2}
    response = client.post(
        "/api/chat",
        json={
            "message": "두 번째 상품 가격",
            "locale": "ko",
            "requestType": "beauty_consultation",
            "chatContext": context,
        },
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["products"][0]["id"] == "b"
    assert response.json()["chatContext"]["session"]["stateVersion"] == 2


@pytest.mark.anyio
async def test_lost_write_acknowledgement_recovers_by_same_request_without_reexecution(setup):
    service, redis, _, _ = setup
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price", "ordinal": 2}
    req = request(ctx)
    redis.fail_after_write = True
    with pytest.raises(ApiError) as exc:
        await service.answer(req, "guest:one")
    assert exc.value.code == "chat_session_unavailable"
    retry = await service.answer(req, "guest:one")
    assert retry.chat_context.session.state_version == 2
    assert service._llm.calls == 2 and redis.writes == 2


@pytest.mark.anyio
async def test_evidence_reference_survives_price_but_is_not_used_as_a_new_fact(setup):
    service, _, repo, _ = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.selected_product_id = "b"
    ctx.shade_selections = {"b": "b-03"}
    service._llm.plan = {"intent": "detail", "ingredientLookup": True}
    ingredients = await service.answer(request(ctx), "guest:one")
    service._llm.plan = {"intent": "price"}
    priced = await service.answer(request(ingredients.chat_context), "guest:one")
    state = await repo.load("guest:one", priced.chat_context.session)
    assert state.evidence_refs[0]["sourceVersion"] == "synthetic-v1"
    assert priced.ingredient_results is None


@pytest.mark.anyio
async def test_client_cannot_extend_expiry_or_change_result_set_id(setup):
    service, _, _, clock = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    service._llm.plan = {"intent": "price", "ordinal": 2}
    ctx.session.result_set_id = uuid4()
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_conflict"
    ctx.session.expires_at = 9999999999
    clock["now"] += 601
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_expired"


def test_process_ttl_setting_and_invalid_configuration(monkeypatch):
    from app.repositories import chat_session_repository as module

    monkeypatch.setattr(module, "get_redis", RedisDouble)
    monkeypatch.setenv("CHAT_SESSION_TTL_SECONDS", "45")
    assert module.get_chat_sessions().ttl_seconds == 45
    monkeypatch.setenv("CHAT_SESSION_TTL_SECONDS", "not-an-integer")
    with pytest.raises(ApiError) as exc:
        module.get_chat_sessions().available()
    assert exc.value.code == "chat_session_config_invalid"


@pytest.mark.anyio
async def test_separate_service_instances_share_canonical_version(setup):
    service, redis, _, _ = setup
    ctx = (await first(setup)).chat_context
    other = ChatService(
        None,
        PlanLlm(intent="price", ordinal=2),
        service._catalog,
        sessions=ChatSessionRepository(redis),
    )
    response = await other.answer(request(ctx), "guest:one")
    assert response.chat_context.session.state_version == 2
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx), "guest:one")
    assert exc.value.code == "chat_session_conflict"


def test_loopback_http_search_then_ordinal_with_mock_redis(client, setup):
    """Actual TCP HTTP; Catalog, LLM and Redis remain explicit test doubles."""
    service = setup[0]
    client.app.dependency_overrides[get_chat_service] = lambda: service
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                client.app,
                log_level="error",
                access_log=False,
                lifespan="off",
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert server.started
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
            ) as http:
                headers = {"X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk"}
                first = http.post(
                    "/api/chat", json=request().model_dump(mode="json"), headers=headers
                )
                assert first.status_code == 200
                service._llm.plan = {"intent": "price", "ordinal": 2}
                response = http.post(
                    "/api/chat",
                    json=request(
                        first.json()["chatContext"],
                        message="두 번째 가격",
                    ).model_dump(mode="json"),
                    headers=headers,
                )
                assert response.status_code == 200
                assert response.json()["products"][0]["id"] == "b"
                assert response.json()["chatContext"]["session"]["stateVersion"] == 2
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.anyio
async def test_explicit_catalog_screen_selection_outside_old_results_is_validated(setup):
    service = setup[0]
    ctx = (await first(setup)).chat_context
    service._llm.plan = {"intent": "price"}
    selected = await service.answer(
        request(
            ctx,
            screen={
                "productId": "c",
                "shadeId": "c-03",
            },
        ),
        "guest:one",
    )
    assert selected.products[0].id == "c" and "25,000" in selected.answer
    assert selected.chat_context.candidate_ids == ["c"]
    assert selected.chat_context.session.result_set_id != ctx.session.result_set_id


@pytest.mark.anyio
@pytest.mark.parametrize("catalog_intent", ["refine", "search"])
async def test_ingredient_filter_survives_budget_search_and_explicit_clear(setup, catalog_intent):
    service, _, _, _ = setup
    calls = []

    async def ingredients(pid, shade, *, ingredient_name=None, operator="includes"):
        calls.append((pid, ingredient_name, operator))
        return CatalogIngredients.model_validate(
            evidence(
                pid=pid,
                shade=shade,
                name=ingredient_name,
                operator=operator,
                ingredients=[{"name": "Alcohol" if pid == "b" else "Water", "sequence": 1}],
            )
        )

    service._catalog.get_ingredients = ingredients
    initial = await first(setup)
    ctx = initial.chat_context.model_copy(deep=True)
    ctx.shade_selections = {"a": "a-03", "b": "b-03"}
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "ingredientName": "Alcohol",
        "ingredientOperator": "excludes",
    }
    filtered = await service.answer(request(ctx), "guest:one")
    assert filtered.chat_context.candidate_ids == ["a"]
    assert filtered.chat_context.shade_selections == {"a": "a-03"}
    before = len(calls)
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 18000}
    budget = await service.answer(request(filtered.chat_context), "guest:one")
    assert budget.chat_context.candidate_ids == ["a"]
    assert calls[before:] == [("a", "Alcohol", "excludes")]
    assert budget.chat_context.filters.ingredient_conditions[0].ingredient_name == "Alcohol"
    # A full catalog search needs explicit shades again; UNKNOWN must not become a recommendation.
    before = len(calls)
    service._llm.plan = {
        "intent": catalog_intent,
        "scope": "catalog",
        "category": "lip",
        "maxPriceKRW": 20000,
    }
    renewed = await service.answer(request(budget.chat_context), "guest:one")
    assert renewed.result_type == "clarification"
    assert next(r for r in renewed.ingredient_results if r.product_id == "b").verdict == "UNKNOWN"
    assert renewed.chat_context.filters.ingredient_conditions
    assert all(call[1:] == ("Alcohol", "excludes") for call in calls[before:])
    assert renewed.chat_context.candidate_ids == [p.id for p in renewed.products]
    stored = await service._sessions.load("guest:one", renewed.chat_context.session)
    assert stored.context.filters == renewed.chat_context.filters
    assert stored.context.shade_selections == renewed.chat_context.shade_selections
    before = len(calls)
    service._llm.plan["shadeName"] = "03"
    renewed = await service.answer(
        request(renewed.chat_context, message="03호로 다시 추천"), "guest:one"
    )
    assert renewed.result_type == "recommendations"
    assert renewed.chat_context.candidate_ids == ["a"]
    assert calls[before:] == [("a", "Alcohol", "excludes"), ("b", "Alcohol", "excludes")]
    assert "Alcohol: 검증된 근거로 요청한 성분 조건을 충족합니다." in renewed.answer
    service._llm.plan = {
        "intent": catalog_intent,
        "scope": "catalog",
        "category": "lip",
        "maxPriceKRW": 20000,
        "clearFilters": ["ingredientConditions"],
    }
    cleared = await service.answer(request(renewed.chat_context), "guest:one")
    assert [p.id for p in cleared.products] == ["a", "b"]
    assert not cleared.chat_context.filters.ingredient_conditions
    assert not cleared.ingredient_results


@pytest.mark.anyio
async def test_new_search_keeps_server_conditions_after_old_product_disappears(setup):
    service, _, repo, _ = setup
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.shade_selections = {"a": "a-03", "b": "b-03"}
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "ingredientName": "Alcohol",
        "ingredientOperator": "excludes",
    }
    filtered = await service.answer(request(ctx), "guest:one")
    service._catalog.products = [p for p in service._catalog.products if p.id != "a"]
    tampered = filtered.chat_context.model_copy(deep=True)
    tampered.filters.ingredient_conditions = []
    service._llm.plan = {"intent": "search", "scope": "catalog", "category": "lip"}
    result = await service.answer(request(tampered), "guest:one")
    assert result.result_type == "clarification" and result.session_status == "stored"
    assert result.chat_context.candidate_ids == ["b", "c"]
    assert result.chat_context.filters.max_price_krw is None
    assert result.chat_context.filters.ingredient_conditions[0].ingredient_name == "Alcohol"
    assert not result.chat_context.shade_selections
    assert not result.chat_context.selected_product_id
    assert all(
        r.verdict == "UNKNOWN" and r.reason == "shade_required" for r in result.ingredient_results
    )
    stored = await repo.load("guest:one", result.chat_context.session)
    assert stored.context.candidate_ids == [p.id for p in result.products]
    assert stored.context.filters == result.chat_context.filters


@pytest.mark.anyio
async def test_persisted_multiple_ingredient_conditions_explain_each_actual_verdict(setup):
    service = setup[0]

    async def ingredients(pid, shade, *, ingredient_name=None, operator="includes"):
        return CatalogIngredients.model_validate(
            evidence(
                pid=pid,
                shade=shade,
                name=ingredient_name,
                operator=operator,
                ingredients=[{"name": "Water", "sequence": 1}],
            )
        )

    service._catalog.get_ingredients = ingredients
    ctx = (await first(setup)).chat_context.model_copy(deep=True)
    ctx.shade_selections = {"a": "a-03", "b": "b-03"}
    for name, operator in [("Water", "includes"), ("Alcohol", "excludes")]:
        service._llm.plan = {
            "intent": "refine",
            "scope": "previous",
            "ingredientName": name,
            "ingredientOperator": operator,
        }
        ctx = (await service.answer(request(ctx), "guest:one")).chat_context
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 18000}
    result = await service.answer(request(ctx), "guest:one")
    assert result.result_type == "recommendations" and [p.id for p in result.products] == ["a"]
    assert "None" not in result.answer
    assert "Water: 검증된 근거로 요청한 성분 조건을 충족합니다." in result.answer
    assert "Alcohol: 검증된 근거로 요청한 성분 조건을 충족합니다." in result.answer
    assert [
        (c.ingredient_name, c.operator, c.verdict) for c in result.ingredient_results[0].conditions
    ] == [
        ("Water", "includes", "MATCH"),
        ("Alcohol", "excludes", "MATCH"),
    ]
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "ingredientName": "Alcohol",
        "ingredientOperator": "includes",
    }
    rejected = await service.answer(request(result.chat_context), "guest:one")
    assert rejected.result_type == "empty" and not rejected.products
    assert not rejected.chat_context.candidate_ids
    assert "조건을 충족합니다" not in rejected.answer


@pytest.mark.anyio
async def test_price_ingredient_refilter_prunes_foreign_shades_before_session_validation(setup):
    service, _, repo, _ = setup
    initial = await first(setup)
    ctx = initial.chat_context.model_copy(deep=True)
    ctx.shade_selections = {"a": "a-03", "b": "b-03"}
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "ingredientName": "향료",
        "ingredientOperator": "includes",
        "maxPriceKRW": 16000,
    }
    result = await service.answer(request(ctx), "guest:one")
    assert result.session_status == "stored" and result.chat_context.candidate_ids == ["a"]
    assert result.chat_context.shade_selections == {"a": "a-03"}
    stored = await repo.load("guest:one", result.chat_context.session)
    assert stored.context.shade_selections == {"a": "a-03"}
    service._llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 1}
    assert (await service.answer(request(result.chat_context), "guest:one")).products[0].id == "a"


def test_ingredient_conditions_accumulate_and_only_explicit_same_name_replaces():
    from app.schemas.chat import BeautyContext, BeautyFilters
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import _effective_filters

    context = BeautyContext(issued_at=1000, filters=BeautyFilters())
    for name, operator in [("Alcohol", "excludes"), ("Water", "includes")]:
        context.filters = _effective_filters(
            context, SearchPlan(intent="refine", ingredient_name=name, ingredient_operator=operator)
        )
    assert [(c.ingredient_name, c.operator) for c in context.filters.ingredient_conditions] == [
        ("Alcohol", "excludes"),
        ("Water", "includes"),
    ]
    context.filters = _effective_filters(context, SearchPlan(intent="search", category="lip"))
    assert len(context.filters.ingredient_conditions) == 2
    updated = _effective_filters(
        context,
        SearchPlan(
            intent="refine", ingredient_name="ＡＬＣＯＨＯＬ", ingredient_operator="includes"
        ),
    )
    assert len(updated.ingredient_conditions) == 2
    assert updated.ingredient_conditions[-1].operator == "includes"
    assert context.filters.ingredient_conditions[0].operator == "excludes"


def test_detail_ingredient_changes_replace_clear_and_respect_limit():
    from app.core.errors import ApiError
    from app.schemas.chat import BeautyContext, BeautyFilters, IngredientFilter
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import _effective_filters

    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(
            ingredient_conditions=[
                IngredientFilter(ingredient_name=f"Ingredient {i}", operator="excludes")
                for i in range(6)
            ]
        ),
    )
    detail = SearchPlan(
        intent="detail",
        persistIngredientConditions=True,
        ingredientName="ingredient 0",
        ingredientOperator="includes",
    )
    replacement = _effective_filters(context, detail)
    assert len(replacement.ingredient_conditions) == 6
    assert replacement.ingredient_conditions[0].operator == "includes"
    seventh = detail.model_copy(update={"ingredient_name": "New"})
    with pytest.raises(ApiError) as exc:
        _effective_filters(context, seventh)
    assert exc.value.code == "ingredient_condition_limit"
    cleared = _effective_filters(
        context,
        seventh.model_copy(
            update={"clear_filters": ["ingredientConditions"]},
        ),
    )
    assert [c.ingredient_name for c in cleared.ingredient_conditions] == ["New"]
