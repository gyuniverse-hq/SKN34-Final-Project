import anyio
import pytest

from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ChatRequest, GraphProduct, SkinHint
from app.services.chat_service import ChatService, build_messages, extract_terms
from tests.conftest import FakeLlm

AUTH = {"Authorization": "Bearer ok-1"}
GUEST = {"X-Vishue-Anonymous-Id": "guest-session-id-0123456789-abcdefghijk"}


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
