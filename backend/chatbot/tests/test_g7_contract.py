from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.schemas.chat import ChatRequest, ChatResponse

AUTH = {"Authorization": "Bearer ok-1"}
GUEST = {"X-Vishue-Anonymous-Id": "guest-session-id-0123456789-abcdefghijk"}
ROOM = "2e36f027-2d57-44a1-b882-38a291d4ce94"
REQUEST = "ef3b54e3-cd78-4ff6-9b27-27fbf4b8403d"
BODY = {
    "message": "hi",
    "conversationId": ROOM,
    "requestId": REQUEST,
    "expectedConversationVersion": 0,
}


def test_persistent_chat_rejects_guest_and_cannot_fake_storage(client):
    guest = client.post("/api/chat", json=BODY, headers=GUEST)
    assert (guest.status_code, guest.json()["code"]) == (403, "persistent_login_required")
    signed_in = client.post("/api/chat", json=BODY, headers=AUTH)
    assert (signed_in.status_code, signed_in.json()["code"]) == (503, "persistence_disabled")


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversationId", "bad"),
        ("requestId", "bad"),
        ("requestId", None),
        ("expectedConversationVersion", None),
        ("expectedConversationVersion", -1),
        ("expectedConversationVersion", True),
        ("expectedConversationVersion", "1"),
    ],
)
def test_persistent_chat_validates_required_fields_even_when_g1_disabled(
    client, monkeypatch, field, value
):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    response = client.post("/api/chat", json={**BODY, field: value}, headers=AUTH)
    assert (response.status_code, response.json()["code"]) == (400, "invalid_request")


def test_legacy_chat_still_ignores_ar_only_request_id(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    request = ChatRequest.model_validate({"message": "hi", "requestId": "not-a-uuid"})
    assert request.request_id is None
    assert ChatResponse(answer="ok", products=[]).model_dump() == {"answer": "ok", "products": []}


def test_persistent_chat_request_id_and_metadata_camel_case(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    request = ChatRequest.model_validate(BODY)
    assert request.request_id == UUID(REQUEST)
    response = ChatResponse.model_validate(
        {
            "answer": "ok",
            "products": [],
            "conversation": {
                "id": ROOM,
                "version": 1,
                "turnId": REQUEST,
                "persistenceStatus": "stored",
            },
        }
    ).model_dump(mode="json")
    assert response["conversation"]["persistenceStatus"] == "stored"


def test_persistent_ar_request_is_rejected(client):
    response = client.post("/api/chat", json={**BODY, "requestType": "ar_command"}, headers=AUTH)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "method,path,body,headers",
    [
        (
            "POST",
            "/api/chat/conversations",
            {"requestId": REQUEST, "entry": {"type": "general"}},
            {},
        ),
        ("GET", "/api/chat/conversations", None, {}),
        ("GET", f"/api/chat/conversations/{ROOM}", None, {}),
        ("DELETE", f"/api/chat/conversations/{ROOM}", None, {}),
        ("GET", f"/api/chat/conversations/{ROOM}/requests/{REQUEST}", None, {}),
        (
            "PATCH",
            f"/api/chat/conversations/{ROOM}/state",
            {
                "requestId": REQUEST,
                "expectedConversationVersion": 0,
                "operation": "clear_selection",
                "payload": {},
            },
            {},
        ),
        ("GET", "/api/chat/memories", None, {}),
        (
            "POST",
            "/api/chat/memories",
            {
                "requestId": REQUEST,
                "proposalId": "proposal",
                "expectedProposalVersion": 1,
                "confirmed": True,
            },
            {},
        ),
        (
            "PATCH",
            f"/api/chat/memories/{ROOM}",
            {
                "requestId": REQUEST,
                "expectedVersion": 1,
                "confirmed": True,
                "value": "coral",
            },
            {},
        ),
        ("DELETE", f"/api/chat/memories/{ROOM}", None, {"Idempotency-Key": REQUEST}),
    ],
)
def test_storage_endpoints_are_closed_even_when_flags_enabled(
    client, monkeypatch, method, path, body, headers
):
    monkeypatch.setattr(get_settings(), "env", "production")
    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", True)
    monkeypatch.setattr(get_settings(), "g7_memory_enabled", True)
    response = client.request(method, path, json=body, headers={**AUTH, **headers})
    assert response.status_code == 503
    assert response.json()["code"] in {"persistence_unavailable", "memory_unavailable"}
    guest = client.request(method, path, json=body, headers={**GUEST, **headers})
    assert guest.status_code == 401


def test_cors_allows_new_methods_and_idempotency_header(monkeypatch):
    monkeypatch.setattr(get_settings(), "cors_origins", ["https://client.example"])
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/chat/memories/" + ROOM,
            headers={
                "Origin": "https://client.example",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization,idempotency-key",
            },
        )
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
