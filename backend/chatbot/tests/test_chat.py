import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import anyio
import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.clients.llm_client import LlmClient
from app.core.errors import ApiError, UpstreamError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.schemas.chat import ChatRequest, GraphProduct, SkinHint
from app.services import chat_service
from app.services.chat_service import ChatService, build_messages, extract_terms, get_chat_service
from tests.conftest import FakeLlm
from tests.test_graph_sync import PRODUCT

AUTH = {"Authorization": "Bearer ok-1"}
GUEST = {"X-Vishue-Anonymous-Id": "guest-session-id-0123456789-abcdefghijk"}


@pytest.mark.parametrize("model,temperature", [("gpt-6-luna", None), ("gpt-4o-mini", 0.3)])
def test_llm_request_uses_supported_temperature_for_model(monkeypatch, model, temperature):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": " answer "}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    messages = [{"role": "user", "content": "hello"}]
    client = LlmClient("https://llm.example.test/v1", "test-key", model, 30)
    assert anyio.run(client.complete, messages) == "answer"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://llm.example.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == model
    assert payload["messages"] == messages
    if temperature is None:
        assert "temperature" not in payload
    else:
        assert payload["temperature"] == temperature


def test_llm_http_errors_still_raise_upstream_error(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(400)), **kwargs
        ),
    )
    client = LlmClient("https://llm.example.test/v1", "test-key", "gpt-6-luna", 30)
    with pytest.raises(UpstreamError):
        anyio.run(client.complete, [{"role": "user", "content": "hello"}])


def test_chat_accepts_guests_with_a_valid_anonymous_session(client):
    missing = client.post("/api/chat", json={"message": "hi"})
    assert (missing.status_code, missing.json()["code"]) == (400, "invalid_request")

    invalid = client.post(
        "/api/chat", json={"message": "hi"}, headers={"X-Vishue-Anonymous-Id": "short"}
    )
    assert (invalid.status_code, invalid.json()["code"]) == (400, "invalid_request")

    guest = client.post("/api/chat", json={"message": "hi"}, headers=GUEST)
    assert guest.status_code == 200


def test_chat_answers_with_graph_products(client, graph):
    res = client.post(
        "/api/chat", json={"message": "Glossy lip tint?", "locale": "ko"}, headers=AUTH
    )
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "Try Rom&nd Juicy Tint."
    assert body["products"] == [
        {"id": "lip-1", "brand": "Rom&nd", "name": "Juicy Tint", "category": "lip"}
    ]
    assert graph.terms == ["glossy", "lip", "tint"]


def test_chat_is_rate_limited_per_principal(client):
    for _ in range(2):
        assert client.post("/api/chat", json={"message": "a b"}, headers=AUTH).status_code == 200
    limited = client.post("/api/chat", json={"message": "a b"}, headers=AUTH)
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    other = {"Authorization": "Bearer ok-2"}
    assert client.post("/api/chat", json={"message": "a b"}, headers=other).status_code == 200


def test_chat_rate_limits_guests_independently(client):
    for _ in range(2):
        assert client.post("/api/chat", json={"message": "a b"}, headers=GUEST).status_code == 200
    assert client.post("/api/chat", json={"message": "a b"}, headers=GUEST).status_code == 429
    other_guest = {"X-Vishue-Anonymous-Id": "other-guest-session-0123456789-abcdefgh"}
    assert client.post("/api/chat", json={"message": "a b"}, headers=other_guest).status_code == 200


def test_chat_validates_message_length(client):
    res = client.post("/api/chat", json={"message": "x" * 1001}, headers=AUTH)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_request"


async def _answer(llm: FakeLlm, graph):
    return await ChatService(graph, llm).answer(ChatRequest(message="tint"))


def test_llm_failures_map_to_api_errors(graph):
    with pytest.raises(ApiError) as err:
        anyio.run(_answer, FakeLlm(configured=False), graph)
    assert (err.value.status, err.value.code) == (503, "chatbot_unavailable")

    with pytest.raises(ApiError) as err:
        anyio.run(_answer, FakeLlm(error=UpstreamError("boom")), graph)
    assert (err.value.status, err.value.code) == (502, "upstream_error")


def test_extract_terms_dedupes_and_keeps_korean():
    assert extract_terms("수분 크림 for dry skin, 수분!") == ["수분", "크림", "for", "dry", "skin"]
    assert len(extract_terms(" ".join(f"w{i}" for i in range(20)))) == 8


def test_prompt_uses_locale_skin_hint_and_only_retrieved_products():
    req = ChatRequest(message="tint", locale="ja", skin=SkinHint(mst=3, undertone="warm"))
    products = [GraphProduct(id="p1", brand="B", name="N", category="lip")]
    system, user = build_messages(req, products)
    assert "Japanese" in system["content"]
    assert '"id": "p1"' in system["content"]
    assert "Monk scale 3, undertone warm" in system["content"]
    assert user == {"role": "user", "content": "tint"}


@pytest.mark.parametrize("question", ["소프트 로즈 메이크업 방법 알려줘", "립 제품 추천해줘"])
def test_empty_catalog_instructions_are_sent_with_each_kind_of_question(question):
    class EmptyGraph:
        async def find_products(self, terms, limit=6):
            return []

    llm = FakeLlm()

    async def answer():
        return await ChatService(EmptyGraph(), llm).answer(ChatRequest(message=question))

    response = anyio.run(answer)
    system, user = llm.messages
    assert response.products == []
    assert user == {"role": "user", "content": question}
    assert "PRODUCTS (JSON): []" in system["content"]
    assert "do not mention\nproduct availability unless the user also asks" in system["content"]
    assert "If the user asks for product recommendations" in system["content"]
    assert "use only products from the PRODUCTS list" in system["content"]


def test_ingredient_explanation_never_uses_graph_or_generated_advice(client, graph, llm):
    response = client.post("/api/chat", json={"message": "판테놀은 어떤 성분이야?"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["claimStatus"] == "not_found" and body["publishedClaims"] == []
    assert body["products"] == [] and not graph.terms and not llm.messages


def ar_payload():
    return {
        "message": "립 진하기를 50%로 설정해 줘.",
        "locale": "ko",
        "requestType": "ar_command",
        "requestId": "0d8b4c3e-8c41-44d2-9b27-9a8e1471a420",
        "arContext": {
            "screenId": "A-01",
            "stateVersion": 7,
            "activeZone": "lip",
            "supportedActions": ["set_intensity"],
            "lip": {"productId": "lip-1", "shadeId": "01", "intensity": 0.65},
        },
    }


class ArTestLlm(FakeLlm):
    def __init__(self, output=None):
        super().__init__()
        self.calls = 0
        self.output = output or json.dumps(
            {
                "status": "proposed",
                "action": {"action": "set_intensity", "zone": "lip", "value": 0.5},
            }
        )

    async def complete(self, messages):
        self.calls += 1
        self.messages = messages
        await asyncio.sleep(0.01)
        return self.output


class ArTestCatalog:
    def __init__(self, product=PRODUCT):
        self.product = product
        self.calls = 0

    async def get_product(self, product_id):
        self.calls += 1
        if isinstance(self.product, Exception):
            raise self.product
        return self.product if self.product and self.product.id == product_id else None


@pytest.fixture
def ar_client(client, graph):
    llm = ArTestLlm()
    catalog = ArTestCatalog(PRODUCT.model_copy(update={"makeup_zone": "lip"}))
    requests = MemoryArRequestRepository()
    client.app.dependency_overrides[get_chat_service] = lambda: ChatService(
        graph, llm, catalog=catalog, requests=requests
    )
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    return client, graph, llm, catalog


@pytest.mark.parametrize("request_type", [None, "chat"])
@pytest.mark.parametrize("question", ["립 제품 추천해줘", "지금 바른 립의 성분 알려줘."])
def test_ar_context_does_not_change_general_chat_routing(client, graph, request_type, question):
    payload = ar_payload()
    payload["message"] = question
    if request_type is None:
        payload.pop("requestType")
    else:
        payload["requestType"] = request_type
    response = client.post("/api/chat", json=payload, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert "arResult" not in body
    if "성분" in question:
        assert body["claimStatus"] == "not_found" and body["products"] == [] and not graph.terms
    else:
        assert set(body) == {"answer", "products"} and graph.terms


@pytest.mark.parametrize("request_type", [None, "chat"])
@pytest.mark.parametrize("question", ["립 제품 추천해줘", "립 성분 알려줘"])
def test_general_chat_ignores_invalid_ar_only_fields(client, graph, request_type, question):
    payload = {
        "message": question,
        "arContext": {"unexpected": "legacy ignored"},
        "requestId": "not-a-uuid",
    }
    if request_type:
        payload["requestType"] = request_type
    response = client.post("/api/chat", json=payload, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert "arResult" not in body
    if "성분" in question:
        assert body["claimStatus"] == "not_found" and body["products"] == [] and not graph.terms
    else:
        assert set(body) == {"answer", "products"} and graph.terms


def test_ar_http_proposes_valid_catalog_selection_without_graph(ar_client):
    client, graph, llm, catalog = ar_client
    response = client.post("/api/chat", json=ar_payload(), headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "products", "arResult"}
    assert body["products"] == []
    result = body["arResult"]
    assert result["status"] == "proposed"
    assert result["requestId"] == ar_payload()["requestId"]
    proposal = result["actionProposal"]
    assert UUID(proposal["commandId"]).version == 4
    assert {k: v for k, v in proposal.items() if k != "commandId"} == {
        "expectedStateVersion": 7,
        "action": "set_intensity",
        "zone": "lip",
        "value": 0.5,
        "productId": "lip-1",
        "shadeId": "01",
    }
    assert graph.terms == []
    assert llm.calls == 1
    assert catalog.calls == 1


def test_ar_service_factory_does_not_initialize_neo4j(monkeypatch):
    def forbidden_graph(*args, **kwargs):
        pytest.fail("AR requests must not initialize Neo4j")

    monkeypatch.setattr(chat_service, "get_driver", forbidden_graph)
    monkeypatch.setattr(chat_service, "GraphRepository", forbidden_graph)
    service = chat_service.get_chat_service(
        llm=ArTestLlm(),
        catalog=ArTestCatalog(PRODUCT.model_copy(update={"makeup_zone": "lip"})),
        requests=MemoryArRequestRepository(),
    )

    async def answer():
        return await service.answer(ChatRequest.model_validate(ar_payload()), "test-owner")

    assert anyio.run(answer).ar_result.status == "proposed"


@pytest.mark.parametrize("product", [None, PRODUCT.model_copy(update={"makeup_zone": "blush"})])
def test_ar_invalid_product_or_zone_cannot_propose(ar_client, product):
    client, graph, llm, catalog = ar_client
    catalog.product = product
    response = client.post("/api/chat", json=ar_payload(), headers=AUTH)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_ar_selection")
    assert graph.terms == []


def test_ar_mismatched_shade_is_rejected_and_same_failure_is_cached(ar_client):
    client, _, llm, _ = ar_client
    payload = ar_payload()
    payload["arContext"]["lip"]["shadeId"] = "other-product-shade"
    first = client.post("/api/chat", json=payload, headers=AUTH)
    second = client.post("/api/chat", json=payload, headers=AUTH)
    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert first.json()["code"] == "invalid_ar_selection"
    assert llm.calls == 1


def test_ar_catalog_outage_does_not_propose(ar_client):
    client, _, _, catalog = ar_client
    catalog.product = UpstreamError("catalog unavailable")
    response = client.post("/api/chat", json=ar_payload(), headers=AUTH)
    assert (response.status_code, response.json()["code"]) == (502, "upstream_error")


def test_ar_retransmission_conflict_and_principal_isolation(ar_client):
    client, _, llm, _ = ar_client
    payload = ar_payload()
    first = client.post("/api/chat", json=payload, headers=AUTH)
    second = client.post("/api/chat", json=payload, headers=AUTH)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert llm.calls == 1
    altered = deepcopy(payload)
    altered["message"] = "립 진하기를 40%로 설정해 줘."
    conflict = client.post("/api/chat", json=altered, headers=AUTH)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "request_conflict")
    other = client.post("/api/chat", json=payload, headers={"Authorization": "Bearer ok-2"})
    assert other.status_code == 200
    other_id = other.json()["arResult"]["actionProposal"]["commandId"]
    first_id = first.json()["arResult"]["actionProposal"]["commandId"]
    assert other_id != first_id
    assert llm.calls == 2


def test_concurrent_identical_ar_requests_call_model_once(ar_client):
    client, _, llm, _ = ar_client

    async def send():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            calls = [http.post("/api/chat", json=ar_payload(), headers=AUTH) for _ in range(2)]
            return await asyncio.gather(*calls)

    first, second = anyio.run(send)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert llm.calls == 1


def _mock_catalog_http(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    return requests


def test_catalog_get_product_reads_a_single_product(monkeypatch):
    product = PRODUCT.model_copy(update={"makeup_zone": "lip"})
    requests = _mock_catalog_http(
        monkeypatch, httpx.Response(200, json={"product": product.model_dump(mode="json")})
    )
    result = anyio.run(CatalogClient("https://catalog.example.test").get_product, "lip-1")
    assert result == product
    assert len(requests) == 1
    assert requests[0].url.path == "/api/products/lip-1"


def test_catalog_get_product_not_found_is_not_a_valid_selection(monkeypatch):
    requests = _mock_catalog_http(monkeypatch, httpx.Response(404))
    assert anyio.run(CatalogClient("https://catalog.example.test").get_product, "missing") is None
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, json={}), httpx.Response(200, content=b"{")],
)
def test_catalog_get_product_upstream_errors_are_not_not_found(monkeypatch, response):
    _mock_catalog_http(monkeypatch, response)
    with pytest.raises(UpstreamError):
        anyio.run(CatalogClient("https://catalog.example.test").get_product, "lip-1")


@pytest.mark.parametrize("product_id", ["../lip-1", "lip/1", "lip?x=1", "lip#fragment", ""])
def test_catalog_get_product_rejects_url_delimiters_without_network(monkeypatch, product_id):
    requests = _mock_catalog_http(monkeypatch, httpx.Response(200, json={}))
    assert anyio.run(CatalogClient("https://catalog.example.test").get_product, product_id) is None
    assert requests == []


def test_ar_production_rejects_process_local_idempotency(ar_client, monkeypatch):
    client, graph, llm, _ = ar_client
    monkeypatch.setattr(chat_service, "get_settings", lambda: SimpleNamespace(is_production=True))
    response = client.post("/api/chat", json=ar_payload(), headers=AUTH)
    assert (response.status_code, response.json()["code"]) == (503, "ar_requests_unavailable")
    assert llm.calls == 0
    assert graph.terms == []


def test_request_capacity_never_evicts_previous_request():
    repository = MemoryArRequestRepository(limit=1)
    request_id = UUID("0d8b4c3e-8c41-44d2-9b27-9a8e1471a420")
    other_id = UUID("0d8b4c3e-8c41-44d2-9b27-9a8e1471a421")
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return object()

    async def run():
        first = await repository.run("user", request_id, "original", factory)
        with pytest.raises(ApiError) as exc:
            await repository.run("user", other_id, "new", factory)
        assert (exc.value.status, exc.value.code) == (503, "ar_requests_unavailable")
        again = await repository.run("user", request_id, "original", factory)
        assert first is again

    anyio.run(run)
    assert calls == 1


def test_cancelled_waiter_does_not_cancel_shared_request():
    repository = MemoryArRequestRepository()
    request_id = UUID("0d8b4c3e-8c41-44d2-9b27-9a8e1471a420")
    calls = 0

    async def run():
        nonlocal calls
        started = asyncio.Event()
        release = asyncio.Event()

        async def factory():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "done"

        first = asyncio.create_task(repository.run("user", request_id, "same", factory))
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(repository.run("user", request_id, "same", factory))
        release.set()
        assert await second == "done"
        assert calls == 1

    anyio.run(run)
