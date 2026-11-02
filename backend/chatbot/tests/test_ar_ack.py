import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import anyio
import httpx
import pytest

from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.schemas.chat import ArAckRequest, ChatResponse
from app.services import chat_service
from app.services.chat_service import ChatService, get_chat_service
from tests.conftest import FakeLlm

AUTH = {"Authorization": "Bearer ok-1"}
OTHER = {"Authorization": "Bearer ok-2"}
REQUEST_ID = "0d8b4c3e-8c41-44d2-9b27-9a8e1471a420"
SESSION_ID = "c847eaa8-4cf9-4e97-8b5d-341d8619f852"
UNKNOWN_COMMAND = "0d8b4c3e-8c41-44d2-9b27-9a8e1471a421"


class JsonLlm(FakeLlm):
    async def complete(self, messages):
        return json.dumps(
            {
                "status": "proposed",
                "action": {"action": "set_intensity", "zone": "lip", "value": 0.5},
            }
        )


class Catalog:
    async def get_product(self, product_id):
        return SimpleNamespace(
            id=product_id, makeup_zone="lip", shades=[SimpleNamespace(id="01")]
        )


def request_body():
    return {
        "message": "립 진하기를 50%로 설정해 줘.",
        "locale": "ko",
        "requestType": "ar_command",
        "requestId": REQUEST_ID,
        "arContext": {
            "screenId": "A-01",
            "stateVersion": 7,
            "activeZone": "lip",
            "supportedActions": ["set_intensity"],
            "lip": {"productId": "lip-1", "shadeId": "01", "intensity": 0.65},
        },
    }


@pytest.fixture
def ack_client(client, graph):
    requests = MemoryArRequestRepository()
    service = ChatService(graph, JsonLlm(), catalog=Catalog(), requests=requests)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    return client, requests


def issue(client):
    response = client.post("/api/chat", json=request_body(), headers=AUTH)
    assert response.status_code == 200
    return response.json()["arResult"]["actionProposal"]["commandId"]


def ack_body(command_id, status="APPLIED"):
    return {
        "requestId": REQUEST_ID,
        "commandId": command_id,
        "sessionId": SESSION_ID,
        "status": status,
        "actualStateVersion": 8,
    }


@pytest.mark.parametrize("status", ["APPLIED", "NO_CHANGE", "REJECTED", "FAILED", "UNKNOWN"])
def test_ack_accepts_each_app_result_and_repeats_idempotently(ack_client, status):
    client, _ = ack_client
    body = ack_body(issue(client), status)
    first = client.post("/api/chat/acks", json=body, headers=AUTH)
    second = client.post("/api/chat/acks", json=body, headers=AUTH)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"received": True}


def test_ack_conflict_cannot_overwrite_first_result(ack_client):
    client, _ = ack_client
    body = ack_body(issue(client))
    assert client.post("/api/chat/acks", json=body, headers=AUTH).status_code == 200
    body["status"] = "FAILED"
    conflict = client.post("/api/chat/acks", json=body, headers=AUTH)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "ar_ack_conflict")
    body["status"] = "APPLIED"
    assert client.post("/api/chat/acks", json=body, headers=AUTH).status_code == 200


def test_ack_requires_owner_and_issued_command(ack_client):
    client, _ = ack_client
    body = ack_body(issue(client))
    no_owner = client.post("/api/chat/acks", json=body)
    assert no_owner.status_code == 400
    other_owner = client.post("/api/chat/acks", json=body, headers=OTHER)
    assert (other_owner.status_code, other_owner.json()["code"]) == (404, "ar_proposal_not_found")
    body["commandId"] = UNKNOWN_COMMAND
    unknown = client.post("/api/chat/acks", json=body, headers=AUTH)
    assert (unknown.status_code, unknown.json()["code"]) == (404, "ar_proposal_not_found")


def test_ack_before_proposal_and_invalid_contract_are_rejected(ack_client):
    client, _ = ack_client
    body = ack_body(UNKNOWN_COMMAND)
    missing = client.post("/api/chat/acks", json=body, headers=AUTH)
    assert (missing.status_code, missing.json()["code"]) == (404, "ar_proposal_not_found")
    for field, value in [("status", "SUCCESS"), ("actualStateVersion", True), ("sessionId", "no")]:
        invalid = {**body, field: value}
        response = client.post("/api/chat/acks", json=invalid, headers=AUTH)
        assert (response.status_code, response.json()["code"]) == (400, "invalid_request")


def test_ack_rejects_pending_and_non_proposal_result():
    repository = MemoryArRequestRepository()
    ack = ArAckRequest.model_validate(ack_body(UNKNOWN_COMMAND))

    async def run():
        started = asyncio.Event()
        finish = asyncio.Event()

        async def work():
            started.set()
            await finish.wait()
            return ChatResponse(answer="No action", products=[])

        pending = asyncio.create_task(repository.run("user", UUID(REQUEST_ID), "hash", work))
        await started.wait()
        with pytest.raises(ApiError) as exc:
            repository.record_ack("user", ack)
        assert (exc.value.status, exc.value.code) == (409, "ar_proposal_pending")
        finish.set()
        await pending
        with pytest.raises(ApiError) as exc:
            repository.record_ack("user", ack)
        assert (exc.value.status, exc.value.code) == (404, "ar_proposal_not_found")

    anyio.run(run)


def test_ack_is_closed_in_production(ack_client, monkeypatch):
    client, _ = ack_client
    body = ack_body(issue(client))
    monkeypatch.setattr(chat_service, "get_settings", lambda: SimpleNamespace(is_production=True))
    response = client.post("/api/chat/acks", json=body, headers=AUTH)
    assert (response.status_code, response.json()["code"]) == (503, "ar_requests_unavailable")


def test_concurrent_same_ack_is_idempotent(ack_client):
    client, _ = ack_client
    body = ack_body(issue(client))

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as http:
            return await asyncio.gather(
                http.post("/api/chat/acks", json=body, headers=AUTH),
                http.post("/api/chat/acks", json=body, headers=AUTH),
            )

    first, second = anyio.run(send)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"received": True}
