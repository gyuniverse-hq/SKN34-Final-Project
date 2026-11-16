"""The E5 driver accepts only identity-bound evidence; test inputs are synthetic."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from tests.g1_e5_live_driver import bind, run
from tests.run_g1_evaluation import CONTRACT, read_jsonl


@pytest.fixture
def sample(tmp_path):
    case = next(
        c for c in read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl") if c["caseId"] == "G1-CAT-01"
    )
    item = {"case": case, "variantId": "free_chat", "environment": "E5", "runId": "r1"}
    image = b"\x89PNG\r\n\x1a\nsynthetic-test-image"
    (tmp_path / "screen.png").write_bytes(image)
    capture = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": "free_chat",
        "environment": "E5",
        "runId": "r1",
        "provenance": {
            "kind": "actual_expo_ui",
            "target": "expo_web",
            "commitSha": "commit",
            "operator": "test",
            "capturedAt": datetime.now(UTC).isoformat(),
        },
        "client": {
            "request": {
                "method": "POST",
                "path": "/api/chat",
                "requestId": "request-1",
                "body": {"message": case["input"]["message"], "requestType": "chat"},
            },
            "response": {"answer": "fixture", "products": []},
            "httpStatus": 200,
        },
        "serverTrace": {"requestId": "request-1", "events": [{"event": "fixture"}]},
        "ui": {"renderedElements": "synthetic accessibility state", "cardIds": []},
        "screen": {"path": "screen.png", "sha256": hashlib.sha256(image).hexdigest()},
        "fixture": {"catalogFixtureRef": "fixture", "fixtureRowSha256": "hash"},
    }
    for field, value, filename in (
        ("clientTrace", capture["client"], "client.json"),
        ("serverTraceFile", capture["serverTrace"], "server.json"),
    ):
        content = json.dumps(value).encode("utf-8")
        (tmp_path / filename).write_bytes(content)
        capture[field] = {"path": filename, "sha256": hashlib.sha256(content).hexdigest()}
    return item, capture


def test_binds_captured_identity_and_artifact_hashes(sample, tmp_path):
    item, capture = sample
    result = bind(item, capture, tmp_path, "commit")
    assert result["observation"]["requestId"] == "request-1"
    assert result["observation"]["ui"]["cardIds"] == []
    assert result["observation"]["status"] == "NOT_RUN"
    assert result["observation"]["blockedReason"] == "ui_capture_origin_not_verified"
    assert len(result["artifacts"]) == 3


@pytest.mark.parametrize("field", ["runId", "variantId", "caseId"])
def test_refuses_wrong_execution_identity(sample, tmp_path, field):
    item, capture = sample
    capture[field] = "different"
    with pytest.raises(ValueError, match="identity"):
        bind(item, capture, tmp_path, "commit")


def test_refuses_mismatched_server_request_and_screen(sample, tmp_path):
    item, capture = sample
    capture["serverTrace"]["requestId"] = "other"
    with pytest.raises(ValueError, match="server_trace"):
        bind(item, capture, tmp_path, "commit")
    capture["serverTrace"]["requestId"] = "request-1"
    capture["screen"]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="screen_hash"):
        bind(item, capture, tmp_path, "commit")


def test_refuses_changed_or_missing_trace_file(sample, tmp_path):
    item, capture = sample
    (tmp_path / "client.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="trace_hash"):
        bind(item, capture, tmp_path, "commit")
    (tmp_path / "client.json").write_text(json.dumps(capture["client"]), encoding="utf-8")
    (tmp_path / "server.json").unlink()
    with pytest.raises(FileNotFoundError):
        bind(item, capture, tmp_path, "commit")


def test_missing_ui_operator_capture_is_not_run(sample, tmp_path, monkeypatch):
    item, _ = sample
    monkeypatch.setenv("G1_E5_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("G1_E5_CAPTURE_TIMEOUT", "0")
    monkeypatch.setattr(
        "tests.g1_e5_live_driver.subprocess.check_output",
        lambda command, **kwargs: "commit" if "rev-parse" in command else "",
    )
    result = run(item)
    assert result["observation"]["status"] == "NOT_RUN"
    assert result["observation"]["blockedReason"] == "operator_ui_capture_missing"


def test_local_endpoints_reject_nonlocal_and_credentials():
    from tests.g1_e5_live_driver import _local_http_url

    assert _local_http_url("http://localhost:8097/") == "http://localhost:8097"
    for endpoint in ("https://localhost:8097", "http://example.com", "http://u:p@localhost:1"):
        with pytest.raises(ValueError):
            _local_http_url(endpoint)


def test_real_trace_join_requires_model_http_and_matching_tool_call():
    from tests.g1_e5_live_driver import _matching_server_events, _verified_catalog_trace

    events = [
        {
            "msg": "g1_model_completion",
            "request_id": "r",
            "model_id": "model",
            "model_response_id": "completion",
            "prompt_version": "v1",
            "tool_call_id": "call1",
        },
        {
            "msg": "catalog_http",
            "request_id": "r",
            "path": "/api/products",
            "status": 200,
            "tool_call_id": "call1",
        },
        {"msg": "g1_catalog_tool_result", "request_id": "r", "tool_call_id": "call1"},
        {"msg": "g1_graph_node_end", "request_id": "r", "node": "plan_turn"},
        {"msg": "g1_graph_node_end", "request_id": "r", "node": "execute_turn"},
        {"msg": "g1_catalog_tool_result", "request_id": "other", "tool_call_id": "secret-other"},
    ]
    lines = [json.dumps(e) for e in events]
    trace = _matching_server_events(lines, "r")
    assert len(trace) == 5
    assert _verified_catalog_trace(trace)
    assert not _verified_catalog_trace(trace[:-1])
    assert not _verified_catalog_trace([trace[0], trace[1] | {"tool_call_id": "other"}, *trace[2:]])
    assert not _verified_catalog_trace([trace[0], trace[1] | {"status": 503}, *trace[2:]])


def test_shared_log_reader_and_redaction(tmp_path):
    from tests.g1_e5_live_driver import _read_shared_log, _safe_response

    path = tmp_path / "log.jsonl"
    path.write_bytes(b"ignored\nactual")
    assert _read_shared_log(path, 8) == b"actual"
    original = {
        "answer": "ok",
        "products": [],
        "chatContext": {"session": {"sessionToken": "private"}},
    }
    sanitized = _safe_response(original)
    assert "session" not in sanitized["chatContext"]
    assert "session" in original["chatContext"]


def test_empty_search_requires_actual_query_result_and_matching_call():
    from tests.g1_e5_live_driver import _verified_empty_search

    events = [
        {"msg": "g1_model_completion", "tool_call_id": "call1"},
        {"msg": "catalog_http", "tool_call_id": "call1", "path": "/api/products", "status": 200},
        {"msg": "g1_catalog_tool_result", "tool_call_id": "call1"},
        {
            "msg": "g1_e5_catalog_search",
            "tool_call_id": "call1",
            "query": "unlikely",
            "result_count": 0,
        },
    ]
    assert _verified_empty_search(events, "unlikely")
    assert not _verified_empty_search(events[:-1], "unlikely")
    assert not _verified_empty_search(events, "other")
    assert not _verified_empty_search(events[:-1] + [events[-1] | {"result_count": 1}], "unlikely")
    assert not _verified_empty_search(
        events[:-1] + [events[-1] | {"tool_call_id": "other"}], "unlikely"
    )
    assert not _verified_empty_search(
        events[:1] + [events[1] | {"status": 503}] + events[2:], "unlikely"
    )


def test_chat_origin_includes_host_port_and_exact_path():
    from tests.g1_e5_live_driver import _matches_chat_origin

    origin = "http://127.0.0.1:8402"
    assert _matches_chat_origin(origin + "/api/chat", origin)
    assert not _matches_chat_origin("http://localhost:8402/api/chat", origin)
    assert not _matches_chat_origin("http://127.0.0.1:9999/api/chat", origin)
    assert not _matches_chat_origin(origin + "/other/api/chat", origin)
    assert not _matches_chat_origin("http://evil@127.0.0.1:8402/api/chat", origin)


def test_server_response_hash_requires_exact_redacted_response():
    from tests.g1_e5_live_driver import _response_hash, _verified_server_response

    body = {
        "answer": "real",
        "products": [{"id": "p"}],
        "chatContext": {"session": {"token": "private"}},
    }
    events = [{"msg": "g1_e5_response_hash", "response_sha256": _response_hash(body)}]
    assert _verified_server_response(
        events, {"products": [{"id": "p"}], "answer": "real", "chatContext": {}}
    )
    assert not _verified_server_response(events, body | {"answer": "changed"})
    assert not _verified_server_response([], body)


def test_response_products_must_be_from_same_observed_tool_call():
    from tests.g1_e5_live_driver import _verified_tool_products

    events = [
        {"msg": "g1_model_completion", "tool_call_id": "c"},
        {"msg": "catalog_http", "tool_call_id": "c", "status": 200, "path": "/api/products"},
        {"msg": "g1_catalog_tool_result", "tool_call_id": "c", "product_ids": ["p", "q"]},
    ]
    assert _verified_tool_products(events, ["p"])
    assert not _verified_tool_products(events, ["other"])
    assert not _verified_tool_products(events[:-1], ["p"])
    assert not _verified_tool_products(
        events[:-1] + [events[-1] | {"tool_call_id": "other"}], ["p"]
    )


def test_rendered_shades_cannot_skip_unknown_or_ambiguous_label():
    from tests.g1_e5_live_driver import _rendered_shade_pairs

    rows = [{"id": "p", "name": "Product", "shades": [{"id": "s", "name": "Shade"}]}]
    assert _rendered_shade_pairs(["Product, Shade"], rows) == [{"productId": "p", "shadeId": "s"}]
    assert _rendered_shade_pairs([], rows) is None
    assert _rendered_shade_pairs(["Product, Shade", "Product, Wrong"], rows) is None
    assert _rendered_shade_pairs(["Product, Shade", "Product, Shade"], rows) is None


def test_socket_owner_requires_listening_port_and_exact_pid(monkeypatch):
    from types import SimpleNamespace

    from tests import g1_e5_live_driver as driver

    monkeypatch.setattr(driver.os, "name", "nt")
    output = "\n".join(
        [
            " TCP    127.0.0.1:8403  0.0.0.0:0  LISTENING  124",
            " TCP    [::1]:8403  [::]:0  LISTENING  124",
            " TCP    127.0.0.1:8403  127.0.0.1:60000  ESTABLISHED  999",
            " TCP    127.0.0.1:8404  0.0.0.0:0  LISTENING  999",
        ]
    )
    monkeypatch.setattr(
        driver.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output)
    )
    assert driver._listening_pids(8403) == {124}
    assert driver._listening_pids(8404) == {999}
    assert driver._listening_pids(8405) == set()


def test_owned_runtime_refuses_dirty_checkout_before_launch(sample, monkeypatch):
    from tests import g1_e5_live_driver as driver

    item, _ = sample
    monkeypatch.setattr(driver.os, "name", "nt")
    monkeypatch.setattr(
        driver.subprocess,
        "check_output",
        lambda command, **kwargs: "abc" if "rev-parse" in command else " M changed.py",
    )

    def forbidden_launch(*args, **kwargs):
        raise AssertionError("dirty checkout must not launch processes")

    monkeypatch.setattr(driver.subprocess, "Popen", forbidden_launch)
    result = driver._run_owned(item)
    assert result["observation"]["status"] == "NOT_RUN"
    assert result["observation"]["blockedReason"] == "worktree_not_clean"


def test_owned_readiness_uses_real_healthz_endpoint():
    from types import SimpleNamespace

    from tests.g1_e5_live_driver import _owned_ready

    class Http:
        def __init__(self, status):
            self.status = status
            self.paths = []

        def get(self, url):
            self.paths.append(url)
            return SimpleNamespace(status_code=self.status.get(url, 404))

    app, chat = "http://localhost:8098", "http://127.0.0.1:8403"
    http = Http({app + "/chat": 200, chat + "/healthz": 200})
    assert _owned_ready(http, app, chat)
    assert http.paths == [app + "/chat", chat + "/healthz"]
    assert not _owned_ready(Http({app + "/chat": 200, chat + "/health": 200}), app, chat)


def test_owned_runtime_preserves_explicit_env_and_sets_cors():
    from tests.g1_e5_live_driver import _owned_environment

    env = _owned_environment(
        {"REDIS_URL": "explicit", "LLM_MODEL": "explicit-model"},
        {"REDIS_URL": "file", "LLM_MODEL": "file-model", "LLM_API_KEY": "file-secret"},
        "http://127.0.0.1:18082",
        8098,
        8403,
    )
    assert env["REDIS_URL"] == "explicit"
    assert env["LLM_MODEL"] == "explicit-model"
    assert env["LLM_API_KEY"] == "file-secret"
    assert json.loads(env["CORS_ORIGINS"]) == ["http://localhost:8098"]
    assert env["EXPO_PUBLIC_CHAT_API_BASE_URL"] == "http://127.0.0.1:8403"
