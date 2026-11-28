import json
from pathlib import Path

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from tests.test_ar_command import JsonLlm
from tests.test_chat import ArTestLlm, ar_payload

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def collected_lip():
    api = json.loads((ROOT / "backend/api/seed/catalog.json").read_text(encoding="utf-8"))
    app = json.loads((ROOT / "lib/devCatalog/oyCatalog.json").read_text(encoding="utf-8"))
    product = next(p for p in api["products"] if p["id"] == "oy-a000000120880")
    bundled = next(p for p in app["products"] if p["id"] == product["id"])
    assert product["makeupZone"] == "lip"
    assert [(s["id"], s["hex"]) for s in product["shades"]] == [
        (s["id"], s["hex"]) for s in bundled["shades"]
    ]
    assert any(s["id"] == "23" for s in product["shades"])
    return product


def catalog(monkeypatch, product):
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.url.path == "/api/products/" + product["id"]
        return httpx.Response(200, json={"product": product})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        "app.clients.catalog_client.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    return CatalogClient("http://catalog.test")


def test_collected_product_proposal_and_guest_ack_over_http(client, monkeypatch, collected_lip):
    llm = ArTestLlm()
    service = ChatService(
        None, llm, catalog(monkeypatch, collected_lip), MemoryArRequestRepository()
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    body = ar_payload()
    body["arContext"]["lip"].update(productId=collected_lip["id"], shadeId="23")
    headers = {"X-Vishue-Anonymous-Id": "2b03dd40-20dc-4b8f-9705-6f91461759f0"}
    response = client.post("/api/chat", json=body, headers=headers)
    assert response.status_code == 200
    proposal = response.json()["arResult"]["actionProposal"]
    assert proposal["productId"] == collected_lip["id"]
    assert proposal["shadeId"] == "23"
    assert proposal["expectedStateVersion"] == body["arContext"]["stateVersion"]
    assert client.post("/api/chat", json=body, headers=headers).json() == response.json()
    assert llm.calls == 1
    ack = {
        "requestId": body["requestId"],
        "commandId": proposal["commandId"],
        "sessionId": "c847eaa8-4cf9-4e97-8b5d-341d8619f852",
        "status": "APPLIED",
        "actualStateVersion": proposal["expectedStateVersion"] + 1,
    }
    # This is a simulated app result, not evidence of real rendering.
    first = client.post("/api/chat/acks", json=ack, headers=headers)
    second = client.post("/api/chat/acks", json=ack, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"received": True}


@pytest.mark.anyio
async def test_foreign_shade_cannot_be_proposed(monkeypatch, collected_lip):
    service = ChatService(
        None, ArTestLlm(), catalog(monkeypatch, collected_lip), MemoryArRequestRepository()
    )
    body = ar_payload()
    body["arContext"]["lip"].update(productId=collected_lip["id"], shadeId="foreign-shade")
    with pytest.raises(ApiError) as error:
        await service.answer(ChatRequest.model_validate(body), "guest:catalog-test")
    assert error.value.code == "invalid_ar_selection"


def test_blush_step_without_lip_via_supervisor(client, monkeypatch):
    products = json.loads((ROOT / "backend/api/seed/catalog.json").read_text("utf-8"))["products"]
    product = next(p for p in products if p.get("makeupZone") == "blush" and p["shades"])
    selection = dict(productId=product["id"], shadeId=product["shades"][0]["id"], intensity=0.4)
    body = ar_payload()
    body.update(message="이거 조금 더 연하게")
    body["arContext"].update(
        activeZone="blush",
        lip=None,
        selections={"blush": selection},
        supportedActions=["set_intensity", "adjust_intensity", "undo"],
    )
    llm = JsonLlm({"operation": "down", "zone": None})
    service = ChatService(None, llm, catalog(monkeypatch, product), MemoryArRequestRepository())
    client.app.dependency_overrides[get_chat_service] = lambda: service
    headers = {"X-Vishue-Anonymous-Id": "2b03dd40-20dc-4b8f-9705-6f91461759f0"}
    response = client.post("/api/chat", json=body, headers=headers)
    assert response.status_code == 200
    result = response.json()
    proposal = result["arResult"]["actionProposal"]
    assert (proposal["zone"], proposal["productId"], proposal["value"]) == (
        "blush",
        product["id"],
        0.3,
    )
    assert result["arResult"]["status"] == "proposed"
    assert client.post("/api/chat", json=body, headers=headers).json() == result
    assert llm.calls == 1
