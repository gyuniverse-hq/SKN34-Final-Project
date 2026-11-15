import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.g1_catalog_tool import G1CatalogTool
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
    with pytest.raises(ApiError) as caught:
        await tool.get_product_detail("a", "foreign-shade")
    assert (caught.value.status, caught.value.code) == (422, "invalid_chat_selection")
