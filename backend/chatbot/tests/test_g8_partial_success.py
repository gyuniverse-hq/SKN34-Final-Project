"""Real parent/adapter execution; synthetic Catalog, model and controlled failures."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.consultation_parent_graph import run_independent_reads
from app.services.conversation_context import prepare_request, revalidate_request, updated_context
from tests.test_beauty_consultation import PlanLlm, product
from tests.test_style_search import Looks, Model


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g8_read_retries", 1)


class Catalog(Looks):
    def __init__(self, failures=2):
        self.failures = failures
        self.style_calls = 0
        self.product_calls = []

    async def get_style_look(self, kind, look_id):
        return SimpleNamespace(id=look_id, title="출근 룩")

    async def get_product(self, pid):
        self.product_calls.append(pid)
        return product(pid, 15000 if pid == "상품가" else 19000)

    async def search_products(self, **kwargs):
        self.product_calls.append(kwargs["q"])
        return [product("상품나", 19000)]

    async def fetch_style_looks(self):
        self.style_calls += 1
        if self.style_calls <= self.failures:
            raise UpstreamError("synthetic Style HTTP 503")
        return await super().fetch_style_looks()


class CombinedModel(PlanLlm, Model):
    def __init__(self):
        PlanLlm.__init__(self, intent="detail", query="상품나")
        Model.__init__(self, [1])

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        if required_tool in {"interpret_consultation_change", "plan_consultation_entry"}:
            import json

            state = json.loads(messages[-1]["content"])
            args = {
                "planId": state["planId"],
                "version": state["version"],
                "action": "delegate" if required_tool == "plan_consultation_entry" else "continue",
            }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": required_tool,
                                        "arguments": json.dumps(args),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }, 0
        return await super().complete_with_tools(messages, tools, required_tool=required_tool)


def request():
    return ChatRequest(
        message='"상품나"와 브랜드 비교하고 비슷한 룩도 찾아줘',
        locale="ko",
        request_type="beauty_consultation",
        chatContext=BeautyContext(
            issued_at=1,
            filters=BeautyFilters(),
            selected_product_id="상품가",
            candidate_ids=["상품가"],
        ),
        styleContext={"kind": "catalog", "lookId": "daily"},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("price_basis", [None, "current_offer"])
async def test_comparison_choices_are_separate_and_revalidated(price_basis):
    from app.schemas.consultation_parent import ParentQuestion
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import execute_beauty

    class Duplicates(Catalog):
        async def search_products(self, **kwargs):
            return [product("상품나 단품", 19000), product("상품나 기획", 25000)]

    catalog = Duplicates(failures=0)
    req = request()
    req._comparison_followup = True
    if price_basis:
        req.message += " 지금 판매 가격도 알려줘"
    reply = await execute_beauty(req, SearchPlan(intent="detail", query="상품나"), catalog)
    assert [c.product_id for c in reply._comparison_choices] == ["상품나 단품", "상품나 기획"]
    assert "1. 상품나 단품" in reply.answer and "2. 상품나 기획" in reply.answer
    assert reply.chat_context.candidate_ids == ["상품가"]
    req._comparison_question = ParentQuestion(
        task_id="product",
        goal="product",
        version=1,
        text=reply.answer,
        input_key="selection",
        comparison_base_id="상품가",
        comparison_price_basis=reply._comparison_price_basis,
        comparison_choices=reply._comparison_choices,
    )
    assert reply._comparison_price_basis == price_basis
    req._comparison_question = ParentQuestion.model_validate_json(
        req._comparison_question.model_dump_json(by_alias=True)
    )
    req.message = "2번"
    selected = await execute_beauty(req, SearchPlan(intent="detail", ordinal=2), catalog)
    assert catalog.product_calls[-2:] == ["상품가", "상품나 기획"]
    if price_basis:
        assert "실제 판매가" in selected.answer and "미확인" in selected.answer
    else:
        assert "앱 등록 가격" in selected.answer
        assert "Catalog" not in selected.answer
    assert selected.chat_context.candidate_ids == ["상품가"]
    req.message = "6번"
    invalid = await execute_beauty(req, SearchPlan(intent="detail", ordinal=6), catalog)
    assert invalid._comparison_choices == reply._comparison_choices
    assert invalid._comparison_price_basis == price_basis
    assert catalog.product_calls[-2:] == ["상품가", "상품나 기획"]
    req.message = "2번. 실시간 말고 앱 등록 가격으로 알려줘"
    changed = await execute_beauty(req, SearchPlan(intent="detail", ordinal=2), catalog)
    assert "앱 등록 가격" in changed.answer
    assert "실제 판매가" not in changed.answer


@pytest.mark.anyio
async def test_comparison_question_restores_and_name_only_answer_reaches_catalog():
    from app.schemas.consultation_parent import ConsultationChange, ConsultationIntent
    from app.services.consultation_intent_service import plan_changes
    from app.services.product_style_consultation_service import try_product_style

    catalog = Catalog(failures=0)
    req = request()
    # G7 restores the verified selection, not an executable candidate session.
    req.chat_context.candidate_ids = []
    initial = await try_product_style(req, catalog, CombinedModel())
    assert initial.chat_context.selected_product_id == "상품가"
    follow = prepare_request(
        req.model_copy(update={"message": "비교 대상만 바꿔줘"}), updated_context({}, initial), []
    )
    change = ConsultationChange(
        task_id="product", operation="update", quote=follow.message, product_operation="compare"
    )
    follow._parent_intent = ConsultationIntent(
        plan_id=follow._consultation_parent.plan_id,
        version=follow._consultation_parent.version,
        action="continue",
        changes=[change],
    )
    follow._consultation_parent, follow._parent_replan = plan_changes(
        follow._consultation_parent, [change]
    )
    pending = await try_product_style(follow, catalog, PlanLlm(intent="detail", query=None))
    assert pending._consultation_parent.question.task_id == "product"
    assert pending._consultation_parent.question.input_key == "selection"
    style_calls = catalog.style_calls
    answer = prepare_request(
        req.model_copy(update={"message": "상품나"}), updated_context({}, pending), []
    )
    change = change.model_copy(update={"quote": answer.message})
    answer._parent_intent = ConsultationIntent(
        plan_id=answer._consultation_parent.plan_id,
        version=answer._consultation_parent.version,
        action="continue",
        changes=[change],
    )
    answer._consultation_parent, answer._parent_replan = plan_changes(
        answer._consultation_parent, [change]
    )
    result = await try_product_style(answer, catalog, PlanLlm(intent="detail", query="상품나"))
    assert catalog.product_calls[-2:] == ["상품가", "상품나"]
    assert catalog.style_calls == style_calls
    assert result._consultation_parent.question is None


@pytest.mark.anyio
@pytest.mark.parametrize("has_candidates", [True, False])
async def test_original_e01_preserves_comparison_and_retries_only_style(
    record_property, has_candidates
):
    import json

    catalog, model = Catalog(), CombinedModel()
    service = ChatService(None, model, catalog)
    req = request()
    if not has_candidates:
        req.chat_context.candidate_ids = []
    await revalidate_request(service, req)
    response = await service.answer(req)
    assert "상품가" in response.answer and "상품나" in response.answer
    assert "확인하지 못했어요" in response.answer and response.style_status == "error"
    assert catalog.product_calls == ["상품가", "상품나"]
    assert catalog.style_calls == 2
    tasks = response._consultation_parent.tasks
    assert [(t.goal, t.status, t.attempts) for t in tasks] == [
        ("product", "completed", 1),
        ("style", "failed", 2),
    ]
    assert len(tasks[1].tool_trace_ids) == 2
    saved = updated_context({}, response)
    # Supply the same server-owned selected scope, as G7 would restore it.
    next_req = prepare_request(req.model_copy(update={"message": "룩만 다시 찾아줘"}), saved, [])
    recovered = await service.answer(next_req)
    assert recovered.style_status == "ready"
    assert "상품가" in recovered.answer and "상품나" in recovered.answer
    assert catalog.product_calls == ["상품가", "상품나"]
    assert model.calls == 1
    record_property(
        "e01_mock",
        json.dumps(
            {
                "modelMode": "mock",
                "catalogMode": "mock",
                "actualExternalCalls": 0,
                "first": response._parent_trace,
                "recovery": recovered._parent_trace,
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_one_transient_failure_recovers_inside_budget():
    catalog = Catalog(failures=1)
    response = await ChatService(None, CombinedModel(), catalog).answer(request())
    assert response.style_status == "ready"
    assert [t.status for t in response._consultation_parent.tasks] == ["completed", "completed"]
    assert catalog.style_calls == 2 and len(catalog.product_calls) == 2


@pytest.mark.anyio
async def test_ambiguous_original_question_does_not_invent_comparison_or_similarity():
    req = ChatRequest(message="브랜드 비교하고 비슷한 룩도 찾아줘", locale="ko")
    catalog = Catalog()
    result = await ChatService(None, CombinedModel(), catalog).answer(req)
    assert not catalog.product_calls and not catalog.style_calls
    assert all(t.status == "waiting_user" for t in result._consultation_parent.tasks)


@pytest.mark.anyio
async def test_deadline_keeps_completed_product(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_deadline_seconds", 0.02)

    async def product_read():
        return ChatResponse(answer="verified product", products=[])

    async def slow_style():
        await asyncio.sleep(1)

    parent, results, _ = await run_independent_reads(
        "compare and look", {"product": product_read, "style": slow_style}, {}
    )
    assert results["product"].answer == "verified product"
    assert parent.tasks[1].reason == "deadline_exceeded"


@pytest.mark.anyio
async def test_nontransient_error_is_not_retried():
    count = 0

    async def invalid():
        nonlocal count
        count += 1
        raise ApiError(400, "invalid", "invalid_input")

    parent, _, _ = await run_independent_reads("compare", {"product": invalid}, {})
    assert count == 1 and parent.tasks[0].reason == "invalid_input"


@pytest.mark.anyio
async def test_write_request_never_enters_read_parent():
    from app.services.product_style_consultation_service import try_product_style

    req = request()
    req.message += " 그리고 AR로 발라줘"
    catalog = Catalog()
    assert await try_product_style(req, catalog, CombinedModel()) is None
    assert not catalog.product_calls and not catalog.style_calls


@pytest.mark.anyio
async def test_changed_scope_never_reuses_previous_comparison():
    catalog = Catalog()
    req = request()
    first = await ChatService(None, CombinedModel(), catalog).answer(req)
    followup = prepare_request(
        req.model_copy(update={"message": "룩만 다시 찾아줘"}), updated_context({}, first), []
    )
    followup.chat_context.selected_product_id = "다른상품"
    before = list(catalog.product_calls)
    result = await ChatService(None, CombinedModel(), catalog).answer(followup)
    assert result.result_type == "clarification" and "조건이 바뀌었" in result.answer
    assert catalog.product_calls == before and catalog.style_calls == 2


@pytest.mark.anyio
async def test_http_style_503_preserves_real_client_product_result(record_property):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.clients.catalog_client import CatalogClient

    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            status = 200
            if self.path == "/api/products/a":
                body = {"product": product("a", 15000).model_dump(mode="json", by_alias=True)}
            elif self.path.startswith("/api/products?"):
                row = product("b", 19000).model_copy(update={"name_ko": "상품나", "name": "상품나"})
                body = {"products": [row.model_dump(mode="json", by_alias=True)]}
            elif self.path == "/api/looks":
                body = {"looks": [{"id": "daily", "title": "출근 룩", "tags": [], "items": []}]}
            else:
                status, body = 503, {"error": "synthetic temporary failure"}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = request()
        req.chat_context.selected_product_id = "a"
        req.chat_context.candidate_ids = ["a"]
        response = await ChatService(
            None, CombinedModel(), CatalogClient(f"http://127.0.0.1:{server.server_port}")
        ).answer(req)
        assert response.style_status == "error"
        assert [t.status for t in response._consultation_parent.tasks] == ["completed", "failed"]
        assert paths.count("/api/products/a") == 1
        assert len([p for p in paths if p.startswith("/api/products?")]) == 1
        assert paths.count("/api/style-looks") == 2
        record_property(
            "e01_http",
            json.dumps(
                {
                    "transport": "real local HTTP",
                    "data": "synthetic",
                    "fault": "Style HTTP 503",
                    "modelMode": "mock",
                    "actualExternalModelCalls": 0,
                    "paths": paths,
                    "trace": response._parent_trace,
                },
                ensure_ascii=False,
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.anyio
@pytest.mark.parametrize("status,expected", [(400, 1), (503, 2)])
async def test_wrapped_http_status_controls_retry(status, expected):
    import httpx

    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        response = httpx.Response(
            status, request=httpx.Request("GET", "http://localhost/synthetic")
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                raise UpstreamError("read failed") from exc
            except UpstreamError as wrapped:
                raise ApiError(502, "read failed", "style_search_unavailable") from wrapped

    await run_independent_reads("synthetic", {"style": read}, {})
    assert calls == expected


@pytest.mark.anyio
async def test_live_catalog_comparison_survives_injected_style_failure(record_property):
    import json
    import os

    from app.clients.catalog_client import CatalogClient

    base = os.environ.get("G8_E01_LIVE_CATALOG")
    if not base:
        pytest.skip("explicit local Catalog required")

    class FaultedCatalog(CatalogClient):
        style_attempts = 0

        async def fetch_style_looks(self):
            self.style_attempts += 1
            raise UpstreamError("synthetic Style availability failure")

    catalog = FaultedCatalog(base)
    candidates = await catalog.search_products()
    candidates = [p for p in candidates if p.price_krw is not None]
    assert len(candidates) >= 2, "real comparison candidates required"
    first, second = candidates[:2]
    name = second.name_ko or second.name
    model = PlanLlm(intent="detail", query=name)
    req = ChatRequest(
        message=f'"{name}"와 비교하고 비슷한 룩도 찾아줘',
        locale="ko",
        request_type="beauty_consultation",
        chatContext=BeautyContext(
            issued_at=1,
            filters=BeautyFilters(),
            selected_product_id=first.id,
            candidate_ids=[first.id],
        ),
        styleConditions=[{"slot": "occasion", "value": "출근"}],
    )
    result = await ChatService(None, model, catalog).answer(req)
    assert [t.status for t in result._consultation_parent.tasks] == ["completed", "failed"]
    assert catalog.style_attempts == 2
    assert (first.name_ko or first.name) in result.answer and name in result.answer
    record_property(
        "e01_live_catalog",
        json.dumps(
            {
                "catalogMode": "live local Catalog HTTP",
                "styleMode": "injected UpstreamError",
                "modelMode": "mock",
                "actualExternalModelCalls": 0,
                "products": [{"id": p.id, "priceKRW": p.price_krw} for p in (first, second)],
                "trace": result._parent_trace,
                "answer": result.answer,
            },
            ensure_ascii=False,
        ),
    )
