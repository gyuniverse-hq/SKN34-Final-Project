import importlib.util
import io
import json
from pathlib import Path

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("publish_eval", HERE / "publish_eval.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
FIXTURE = HERE.parents[1] / "backend/api/tests/fixtures/admin_eval_v2.json"


def test_v2_payload_sends_only_strict_summary_with_mock_http():
    value = json.loads(FIXTURE.read_text(encoding="utf8"))
    captured = []
    def sender(request, timeout):
        captured.append(request)
        return io.BytesIO(b'{"id":"mock","kind":"human"}')
    assert publisher.publish(value, "http://127.0.0.1:8000", "memory-only-token", sender)["id"] == "mock"
    body = json.loads(captured[0].data)
    assert body["summaryJson"]["reliability"]["raterCount"] == 5
    assert b"memory-only-token" not in captured[0].data
    assert "source_files" not in json.dumps(body)


def test_modified_payload_and_insecure_destination_are_rejected():
    value = json.loads(FIXTURE.read_text(encoding="utf8"))
    with pytest.raises(ValueError):
        publisher.publish(value, "http://example.com", "token")
    value["summaryJson"]["imageId"] = "secret"
    with pytest.raises(ValueError):
        publisher.publish(value, "http://127.0.0.1", "token")
