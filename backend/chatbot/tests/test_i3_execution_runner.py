"""Observer unit checks; stubs here are not service-evaluation results."""

import json
from hashlib import sha256
from uuid import UUID

import httpx
import pytest

from tests.i3_execution_observer import (
    ObservationCapture,
    project_session,
    redact,
    snapshot_session,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REQUEST = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OWNER = "guest:fixture-isolated"


class ReadOnlyRedis:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or {}
        self.fail = fail
        self.keys = []

    async def get(self, key):
        self.keys.append(key)
        if self.fail:
            raise OSError("sensitive diagnostic must not escape")
        return self.rows.get(key)


def sample_state():
    return {
        "sessionId": SESSION,
        "owner": OWNER,
        "ownerKind": "guest",
        "tokenHash": "sensitive-hash",
        "resultSetId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "stateVersion": 2,
        "lastRequestId": REQUEST,
        "context": {
            "candidateIds": ["product-a", "product-b"],
            "scopeIds": ["product-a", "product-b"],
            "selectedProductId": "product-b",
            "filters": {
                "ingredientConditions": [{"ingredientName": "test", "operator": "excludes"}],
                "maxPriceKRW": 20000,
            },
        },
        "optionContext": {
            "selections": {"product-b": "option-b"},
            "categoryId": "cream",
            "priceBasis": "collected_sale",
            "requireInStock": False,
        },
        "lastResponse": {"sessionToken": "sensitive-token"},
    }


def test_recursive_redaction_keeps_raw_structure_without_capability_secrets():
    raw = {
        "chatContext": {"session": {"sessionToken": "token", "sessionId": SESSION}},
        "Authorization": "bearer key",
        "owner": "guest:private",
        "nested": [{"access_token": "private", "tokenHash": "hash", "value": 3}],
    }
    safe = redact(raw)
    assert safe["chatContext"]["session"]["sessionToken"] == "[REDACTED]"
    assert safe["chatContext"]["session"]["sessionId"] == SESSION
    assert safe["Authorization"] == safe["owner"] == "[REDACTED]"
    assert safe["nested"] == [{"access_token": "[REDACTED]", "tokenHash": "[REDACTED]", "value": 3}]
    assert raw["chatContext"]["session"]["sessionToken"] == "token"


def test_projection_is_from_redis_data_only_and_excludes_owner_token_and_cached_response():
    state = sample_state()
    projected = project_session(json.dumps(state))
    assert projected == {
        "exists": True,
        "sessionId": SESSION,
        "stateVersion": 2,
        "resultSetId": state["resultSetId"],
        "lastRequestId": REQUEST,
        "candidateIds": ["product-a", "product-b"],
        "scopeIds": ["product-a", "product-b"],
        "selectedProductId": "product-b",
        "ingredientConditions": [{"ingredientName": "test", "operator": "excludes"}],
        "maxPriceKRW": 20000,
        "optionSelections": {"product-b": "option-b"},
        "priceBasis": "collected_sale",
        "requireInStock": False,
        "categoryId": "cream",
    }
    assert "sensitive" not in repr(projected) and OWNER not in repr(projected)


def test_missing_optional_state_fields_are_not_synthesized():
    state = sample_state()
    state.pop("optionContext")
    state["context"].pop("selectedProductId")
    state["context"]["filters"].pop("maxPriceKRW")
    result = project_session(state)
    assert "optionSelections" not in result
    assert "selectedProductId" not in result
    assert "maxPriceKRW" not in result


@pytest.mark.anyio
async def test_fresh_absence_needs_confirmed_index_read():
    client = ReadOnlyRedis()
    assert await snapshot_session(client, owner=OWNER, request_id=REQUEST, fresh=True) == {
        "exists": False
    }
    expected = f"vishue:chat:request:{sha256(OWNER.encode()).hexdigest()}:{REQUEST}"
    assert client.keys == [expected]
    assert await snapshot_session(client, owner=OWNER, request_id=REQUEST) is None
    assert (
        await snapshot_session(
            ReadOnlyRedis(fail=True), owner=OWNER, request_id=REQUEST, fresh=True
        )
        is None
    )
    assert await snapshot_session(None, owner=OWNER, request_id=REQUEST, fresh=True) is None


@pytest.mark.anyio
async def test_index_and_session_reads_project_real_matching_record():
    request_key = f"vishue:chat:request:{sha256(OWNER.encode()).hexdigest()}:{REQUEST}"
    session_key = f"vishue:chat:session:{SESSION}"
    client = ReadOnlyRedis({request_key: SESSION.encode(), session_key: json.dumps(sample_state())})
    state = await snapshot_session(client, owner=OWNER, request_id=REQUEST, fresh=True)
    assert state["exists"] and state["sessionId"] == SESSION
    assert state["optionSelections"] == {"product-b": "option-b"}
    assert client.keys == [request_key, session_key]
    assert (await snapshot_session(ReadOnlyRedis(), session_id=SESSION)) == {"exists": False}


@pytest.mark.anyio
async def test_bad_redis_records_or_ids_remain_unobserved():
    state = sample_state()
    state["sessionId"] = str(UUID(int=2))
    client = ReadOnlyRedis({f"vishue:chat:session:{SESSION}": json.dumps(state)})
    assert await snapshot_session(client, session_id=SESSION) is None
    assert await snapshot_session(client, session_id="not-an-id") is None
    client.rows[f"vishue:chat:session:{SESSION}"] = "not json"
    assert await snapshot_session(client, session_id=SESSION) is None


@pytest.mark.anyio
async def test_observes_plan_and_catalog_without_replacing_results(monkeypatch):
    from app.services import chat_service

    class Plan:
        def model_dump(self, **kwargs):
            return {"intent": "search", "ingredientConditions": [{"operator": "excludes"}]}

    plan = Plan()

    async def interpret(*args, **kwargs):
        return plan

    monkeypatch.setattr(chat_service, "interpret_beauty", interpret)
    original = httpx.AsyncClient.request

    def serve(request):
        return httpx.Response(200, json={"claims": [], "sessionToken": "private"})

    with ObservationCapture("http://127.0.0.1:45001") as capture:
        assert await chat_service.interpret_beauty(None, None) is plan
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            response = await client.post(
                "http://127.0.0.1:45001/api/catalog/ingredient-claims/search",
                json={"use": "explain", "sessionToken": "private"},
            )
            await client.get("http://127.0.0.1:45002/other")
        assert response.status_code == 200 and response.json()["sessionToken"] == "private"
    assert httpx.AsyncClient.request is original
    assert capture.trace["plan"]["intent"] == "search"
    assert capture.trace["claimRequests"][0] == {"use": "explain", "sessionToken": "[REDACTED]"}
    assert capture.trace["claimResponses"][0]["httpStatus"] == 200
    assert capture.trace["claimResponses"][0]["response"]["sessionToken"] == "[REDACTED]"
    assert len(capture.trace["catalogRequests"]) == 1


@pytest.mark.anyio
async def test_failed_network_call_is_recorded_then_reraised():
    def fail(request):
        raise httpx.ConnectError("private text", request=request)

    with ObservationCapture("http://127.0.0.1:45001") as capture:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("http://127.0.0.1:45001/api/catalog/categories")
    assert capture.trace["catalogRequests"] == [
        {"method": "GET", "path": "/api/catalog/categories", "transportError": "ConnectError"}
    ]


@pytest.mark.anyio
async def test_non_json_http_response_is_not_fabricated():
    with ObservationCapture("http://127.0.0.1:45001") as capture:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(503, text="unavailable"))
        ) as client:
            result = await client.post(
                "http://127.0.0.1:45001/api/catalog/ingredient-claims/search",
                json={"use": "avoid"},
            )
    assert result.status_code == 503
    assert capture.trace["claimResponses"] == [{"httpStatus": 503}]
    assert capture.trace["catalogRequests"][0]["responseUnavailable"] is True


@pytest.mark.anyio
async def test_catalog_query_parameters_are_observed_and_redacted():
    with ObservationCapture("http://127.0.0.1:45001") as capture:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"products": []}))
        ) as client:
            await client.get(
                "http://127.0.0.1:45001/api/products?category=lip&token=private",
                params={"ingredientName": "test", "api_key": "private"},
            )
    entry = capture.trace["catalogRequests"][0]
    assert entry["query"] == [{"category": "lip"}, {"token": "[REDACTED]"}]
    assert entry["params"] == {"ingredientName": "test", "api_key": "[REDACTED]"}
    assert "private" not in repr(entry)


def test_runner_mapping_changes_only_declared_exact_identifiers():
    from tests.i3_execution_runner import transformed

    original = {
        "productId": "oy-syn-a",
        "answer": "oy-syn-a is a product",
        "nested": {"oy-syn-a": ["syn-a-01", "unknown"]},
    }
    result = transformed(original, {"oy-syn-a": "syn-a", "syn-a-01": "syn-a-01"})
    assert result["productId"] == "syn-a"
    assert result["answer"] == "oy-syn-a is a product"
    assert result["nested"] == {"syn-a": ["syn-a-01", "unknown"]}
    assert original["productId"] == "oy-syn-a"


def test_container_verification_rejects_wrong_owner_or_public_port(monkeypatch):
    from tests import i3_execution_runner as runner

    item = {
        "Id": "owned",
        "Config": {
            "Image": "redis:7-alpine",
            "Labels": {
                "com.docker.compose.project": "dedicated",
                "com.docker.compose.service": "redis",
                "io.vishue.i3-eval.run-id": "run",
                "io.vishue.i3-eval.purpose": "synthetic-only",
            },
        },
        "NetworkSettings": {"Ports": {"6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": "45678"}]}},
    }
    monkeypatch.setattr(runner, "inspect", lambda _: item)
    assert (
        runner.verify_container("owned", "dedicated", "run", "redis", "redis:7-alpine", 6379)
        == 45678
    )
    with pytest.raises(RuntimeError):
        runner.verify_container("owned", "other", "run", "redis", "redis:7-alpine", 6379)
    item["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostIp"] = "0.0.0.0"
    with pytest.raises(RuntimeError):
        runner.verify_container("owned", "dedicated", "run", "redis", "redis:7-alpine", 6379)


def test_child_environment_never_inherits_actual_credentials(monkeypatch):
    from tests.i3_execution_runner import sanitized_environment

    monkeypatch.setenv("LLM_API_KEY", "private-llm-key")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "private-service-key")
    monkeypatch.setenv("PYTHONPATH", "untrusted-path")
    env = sanitized_environment("postgresql+asyncpg://i3_eval:i3_eval@127.0.0.1:1234/i3_eval", 1235)
    assert env["LLM_API_KEY"] == ""
    assert "SUPABASE_SECRET_KEY" not in env and "PYTHONPATH" not in env
    assert env["REDIS_URL"] == "redis://127.0.0.1:1235/0"


def test_setup_failure_keeps_cleanup_failure_and_original_cause(monkeypatch):
    from tests import i3_execution_runner as runner

    monkeypatch.setattr(runner, "unique_environment", lambda: ("run", "project", {}))
    monkeypatch.setattr(runner, "project_objects", lambda *args: ["owned"])

    def fail_setup(*args, **kwargs):
        raise RuntimeError("setup broke")

    def fail_cleanup(*args, **kwargs):
        raise RuntimeError("cleanup broke")

    monkeypatch.setattr(runner, "docker", fail_setup)
    monkeypatch.setattr(runner, "cleanup", fail_cleanup)
    with pytest.raises(RuntimeError, match="setup broke.*cleanup broke"):
        runner.start_environment()


@pytest.mark.anyio
async def test_cleanup_failure_preserves_actual_observations(monkeypatch):
    from types import SimpleNamespace

    from tests import i3_execution_runner as runner

    monkeypatch.setattr(
        runner,
        "start_environment",
        lambda: ("run", "project", {}, ["owned"], {}, 1000, 1001),
    )
    manifest = {
        "fixtureHash": "hash",
        "logicalToPhysicalProduct": {"logical": "physical"},
        "logicalToPhysicalOption": {},
    }
    monkeypatch.setattr(runner, "seed_environment", lambda *args: ({}, manifest))
    sock = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1002), close=lambda: None)
    monkeypatch.setattr(runner, "allocate_socket", lambda: sock)
    proc = SimpleNamespace(terminate=lambda: None, wait=lambda **kwargs: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(runner, "wait_api", lambda *args: None)

    async def observed(*args):
        return [{"productId": "physical"}], None

    monkeypatch.setattr(runner, "execute_chat", observed)

    def fail_cleanup(*args):
        raise RuntimeError("daemon read-only")

    monkeypatch.setattr(runner, "cleanup", fail_cleanup)
    raw, scored, details = await runner.run_scenario(
        SimpleNamespace(fixtureRef="Q01", fixtureHash="hash"), [], None
    )
    assert raw == [{"productId": "physical"}]
    assert scored == [{"productId": "logical"}]
    assert details["containerIds"] == ["owned"]
    assert details["cleanupErrors"] == ["RuntimeError: daemon read-only"]


def test_malformed_http_response_is_preserved_for_fail_not_blocked():
    from tests.i3_execution_runner import parse_chat_response

    array, digest = parse_chat_response(httpx.Response(200, json=["invalid"]))
    assert array == ["invalid"] and digest is None
    body, digest = parse_chat_response(httpx.Response(503, content=b"private invalid body"))
    assert body is None and digest == sha256(b"private invalid body").hexdigest()
