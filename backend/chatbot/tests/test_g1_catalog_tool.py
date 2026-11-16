import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import create_app
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from app.services.g1_catalog_tool import G1CatalogTool, InvalidShadeSelection
from tests.test_beauty_consultation import PlanLlm, product


@pytest.fixture
def anyio_backend():
    return "asyncio"


def row(pid, *, brand="롬앤", category="lip", description=""):
    item = product(pid, 15000, category=category, description=description)
    return item.model_copy(update={"brand": brand}).model_dump(by_alias=True)


def catalog_client(monkeypatch, handler):
    http_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: http_client(transport=transport, **kwargs)
    )
    return CatalogClient("http://catalog.test")


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["chat", "beauty_consultation"])
async def test_both_entries_use_catalog_http_and_verify_category_and_brand(monkeypatch, kind):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "products": [
                    row("a"),
                    row("b", brand="유리아쥬", description="롬앤 발색 비교"),
                    row("c", category="cheek"),
                ]
            },
        )

    service = ChatService(
        None,
        PlanLlm(intent="search", category="lip", query="롬앤"),
        catalog_client(monkeypatch, handler),
    )
    result = await service.answer(
        ChatRequest(
            message="롬앤 립 제품 추천해 줘",
            request_type=kind,
            locale="ko",
        )
    )
    assert [p.id for p in result.products] == ["a"]
    assert result.supervisor.result.evidence[0].source == "catalog_api"
    assert [(r.method, r.url.path, dict(r.url.params)) for r in requests] == [
        ("GET", "/api/products", {"category": "lip", "q": "롬앤"})
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["status", "timeout", "json", "duplicate"])
async def test_catalog_failure_is_not_a_successful_empty_search(monkeypatch, fault):
    def handler(request):
        if fault == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if fault == "status":
            return httpx.Response(503)
        if fault == "json":
            return httpx.Response(200, content=b"not JSON")
        return httpx.Response(200, json={"products": [row("a"), row("a")]})

    with pytest.raises(UpstreamError):
        await G1CatalogTool(catalog_client(monkeypatch, handler)).search_products(category="lip")


@pytest.mark.anyio
async def test_empty_and_missing_are_normal_catalog_results(monkeypatch):
    def handler(request):
        if request.url.path == "/api/products":
            return httpx.Response(200, json={"products": []})
        return httpx.Response(404, json={"code": "not_found"})

    tool = G1CatalogTool(catalog_client(monkeypatch, handler))
    assert await tool.search_products(q="missing") == []
    assert await tool.get_product_detail("missing", None) is None


@pytest.mark.anyio
async def test_g1_does_not_promote_fragrance_or_reference_price(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"products": [row("a")]})

    result = await ChatService(
        None,
        PlanLlm(intent="search", category="lip", fragranceFree=True, maxPriceKRW=20000),
        catalog_client(monkeypatch, handler),
    ).answer(ChatRequest(message="2만원 이하 무향료 립 추천해 줘", locale="ko"))
    assert paths == ["/api/products"]
    assert [p.id for p in result.products] == ["a"]
    assert "기준가격" in result.answer and "무향료 여부는 미확인" in result.answer
    assert any(
        condition.condition == "fragranceFree" and condition.verdict == "UNKNOWN"
        for condition in result.supervisor.result.conditions
    )


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["product_id", "shade_owner", "shade_duplicate"])
async def test_detail_rejects_inconsistent_catalog_identities(monkeypatch, fault):
    payload = row("b" if fault == "product_id" else "a")
    if fault == "shade_owner":
        payload["shades"][0]["productId"] = "unrelated"
    if fault == "shade_duplicate":
        payload["shades"].append(payload["shades"][0])
    tool = G1CatalogTool(
        catalog_client(monkeypatch, lambda _: httpx.Response(200, json={"product": payload}))
    )
    with pytest.raises(UpstreamError):
        await tool.get_product_detail("a", None)


@pytest.mark.anyio
async def test_detail_verifies_screen_shade_ownership(monkeypatch):
    tool = G1CatalogTool(
        catalog_client(monkeypatch, lambda _: httpx.Response(200, json={"product": row("a")}))
    )
    assert (await tool.get_product_detail("a", "real-shade")).id == "a"
    with pytest.raises(InvalidShadeSelection):
        await tool.get_product_detail("a", "foreign-shade")


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["chat", "beauty_consultation"])
@pytest.mark.parametrize("enabled", [True, False])
async def test_foreign_screen_shade_returns_safe_clarification(monkeypatch, kind, enabled):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", enabled)
    calls = []
    real_async_client = httpx.AsyncClient

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"product": row("a")})

    class DetailLlm(PlanLlm):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            return {
                "id": "fixture-completion",
                "model": "fixture-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "fixture-call",
                                    "type": "function",
                                    "function": {
                                        "name": "catalog_get_product_detail",
                                        "arguments": "{}",
                                    },
                                }
                            ]
                        },
                    }
                ],
            }, 1

    class EmptyGraph:
        async def find_products(self, terms):
            return []

    service = ChatService(
        EmptyGraph(), DetailLlm(intent="detail"), catalog_client(monkeypatch, handler)
    )
    app = create_app()
    from app.core.auth import ChatPrincipal, chat_principal

    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[chat_principal] = lambda: ChatPrincipal(rate_limit_key="fixture")
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    payload = {
        "message": "현재 선택한 05호가 어떤 색이야?",
        "requestType": kind,
        "locale": "ko",
        "screenContext": {"screenId": "product-detail", "productId": "a", "shadeId": "05"},
    }
    async with real_async_client(
        transport=httpx.ASGITransport(app=app), base_url="http://chat.test"
    ) as client:
        response = await client.post("/api/chat", json=payload)
        valid = None
        if enabled:
            payload["screenContext"]["shadeId"] = "real-shade"
            valid = await client.post("/api/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] and body["products"] == []
    if enabled:
        assert body.get("resultType") == "clarification"
        assert "05" not in body["answer"]
        context = body.get("chatContext") or {}
        assert not context.get("selectedProductId")
        assert not context.get("shadeSelections")
        assert valid.status_code == 200
        valid_body = valid.json()
        assert valid_body["resultType"] == "product_detail"
        assert valid_body["chatContext"]["shadeSelections"] == {"a": "real-shade"}
        assert calls == ["/api/products/a", "/api/products/a"]


@pytest.mark.anyio
async def test_g1_moisture_preference_does_not_claim_verified_match(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)

    def handler(request):
        return httpx.Response(200, json={"products": [row("a")]})

    response = await ChatService(
        None,
        PlanLlm(intent="search", category="lip", moisturizing=True, maxPriceKRW=20000),
        catalog_client(monkeypatch, handler),
    ).answer(ChatRequest(message="2만원 이하 촉촉한 립 추천해줘", locale="ko"))

    assert [product.id for product in response.products] == ["a"]
    assert "조건에 맞는 후보" not in response.answer
    assert "확인 가능한 상품 후보" in response.answer
    assert "보습 효과를 보장하지" in response.answer
