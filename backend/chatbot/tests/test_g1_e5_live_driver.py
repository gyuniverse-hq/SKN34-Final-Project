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
