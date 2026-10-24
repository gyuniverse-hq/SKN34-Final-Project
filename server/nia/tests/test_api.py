"""HTTP contract and resource-boundary tests; no pretrained weights or network."""

import io
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, UnidentifiedImageError

from server.nia import api
from server.nia.face_detection import ROI_METHOD, YuNetRegions

TOKEN = "test-only-secret-" + "x" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}


def result():
    return {
        "schema_version": "skin-recommendation-features-v1",
        "status": "complete",
        "features": {"acne": 0},
        "feature_status": {"acne": "predicted"},
        "provenance": {},
        "roi_method": ROI_METHOD,
        "validation_status": "experimental_unvalidated",
        "training_roi_match": False,
        "softmax_calibrated": False,
        "unsupported": [],
        "indicators": ["acne", "pore", "pigmentation", "wrinkle"],
        "acne": {"status": "predicted", "score": 0.1, "label": 0},
    }


class RuntimeFixture:
    gpu = "test GPU"

    def __init__(self):
        self.calls = []
        self.closed = False
        self.failure = None

    def analyze(self, raw):
        self.calls.append(raw)
        if self.failure:
            raise self.failure
        return result()

    def close(self):
        self.closed = True


@pytest.fixture
def setup():
    runtime = RuntimeFixture()
    settings = api.Settings(
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="test-public",
        gpu_uuid="GPU-test",
    )
    factory = Mock(return_value=runtime)
    app = api.create_app(
        settings,
        runtime_factory=factory,
        verifier_factory=lambda *args: Mock(
            verify=AsyncMock(
                side_effect=lambda token: (
                    {"sub": "user", "role": "authenticated"} if token == TOKEN else None
                )
            )
        ),
    )
    with TestClient(app) as client:
        yield client, runtime, factory, app
    assert runtime.closed


def test_startup_loads_once_and_responses_keep_the_existing_schema(setup):
    client, runtime, factory, _app = setup
    assert factory.call_count == 1
    for _ in range(2):
        response = client.post(
            "/analyze", files={"file": ("capture.jpg", b"jpeg", "image/jpeg")}, headers=AUTH
        )
        assert response.status_code == 200
        assert response.json() == result()
        assert response.headers["cache-control"] == "no-store"
    assert runtime.calls == [b"jpeg", b"jpeg"]
    assert factory.call_count == 1
    health = client.get("/health", headers=AUTH)
    assert health.json() == {
        "status": "ready",
        "device": "cuda:0",
        "gpu": "test GPU",
        "models_loaded": 4,
    }


def test_temporary_test_token_mode_does_not_require_supabase():
    runtime = RuntimeFixture()
    settings = api.Settings(
        gpu_uuid="GPU-test",
        auth_mode="test-token",
        test_bearer_token=TOKEN,
    )
    app = api.create_app(
        settings,
        runtime_factory=Mock(return_value=runtime),
        verifier_factory=Mock(side_effect=AssertionError("Supabase must not be used in test-token mode")),
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers=AUTH).status_code == 200
        assert client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert runtime.closed


def test_temporary_test_token_must_be_long_and_explicit():
    with pytest.raises(ValueError, match="32 bytes"):
        api.Settings(gpu_uuid="GPU-test", auth_mode="test-token", test_bearer_token="short")
    with pytest.raises(ValueError, match="SKIN_AUTH_MODE"):
        api.Settings(gpu_uuid="GPU-test", auth_mode="none")


@pytest.mark.parametrize("path,method", [("/analyze", "post"), ("/health", "get")])
@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic anything"])
def test_authentication_before_body_parsing(setup, monkeypatch, path, method, header):
    client, runtime, _, _ = setup
    parser = Mock(side_effect=AssertionError("An unauthenticated body must not be parsed"))
    monkeypatch.setattr(api, "image_bytes", parser)
    headers = {} if header is None else {"Authorization": header}
    response = getattr(client, method)(path, headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert not parser.called and not runtime.calls


def test_no_unauthenticated_documentation_routes(setup):
    client, _, _, _ = setup
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_large_camera_upload_does_not_spool_to_disk(setup, monkeypatch):
    client, runtime, _, _ = setup
    monkeypatch.setattr(tempfile, "TemporaryFile", Mock(side_effect=AssertionError("disk write")))
    raw = b"camera-jpeg" * 180000
    response = client.post(
        "/analyze", files={"file": ("../untrusted.jpg", raw, "image/jpeg")}, headers=AUTH
    )
    assert response.status_code == 200
    assert runtime.calls == [raw]


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png"])
def test_raw_encoded_image_upload(setup, mime):
    client, runtime, _, _ = setup
    response = client.post("/analyze", content=b"image", headers={**AUTH, "Content-Type": mime})
    assert response.status_code == 200 and runtime.calls == [b"image"]


def test_body_limit_even_without_content_length(setup):
    client, runtime, _, app = setup
    app.state.settings = replace(app.state.settings, max_upload_bytes=1024)
    response = client.post(
        "/analyze",
        content=iter([b"x" * 700, b"y" * 700]),
        headers={**AUTH, "Content-Type": "image/jpeg"},
    )
    assert response.status_code == 413 and not runtime.calls


def test_declared_body_limit_rejected(setup):
    client, runtime, _, app = setup
    app.state.settings = replace(app.state.settings, max_upload_bytes=1024)
    response = client.post(
        "/analyze", content=b"x" * 1025, headers={**AUTH, "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 413 and not runtime.calls


@pytest.mark.parametrize("mime", ["application/json", "image/heic", "text/plain"])
def test_unsupported_formats(setup, mime):
    client, runtime, _, _ = setup
    response = client.post("/analyze", content=b"x", headers={**AUTH, "Content-Type": mime})
    assert response.status_code == 415 and not runtime.calls


def test_empty_and_malformed_uploads(setup):
    client, runtime, _, _ = setup
    assert (
        client.post(
            "/analyze", content=b"", headers={**AUTH, "Content-Type": "image/jpeg"}
        ).status_code
        == 422
    )
    response = client.post(
        "/analyze", content=b"broken", headers={**AUTH, "Content-Type": "multipart/form-data"}
    )
    assert response.status_code == 400
    response = client.post("/analyze", files={"wrong": ("a.jpg", b"x", "image/jpeg")}, headers=AUTH)
    assert response.status_code == 422
    response = client.post(
        "/analyze",
        files=[("file", ("a.jpg", b"x", "image/jpeg")), ("file", ("b.jpg", b"x", "image/jpeg"))],
        headers=AUTH,
    )
    assert response.status_code == 400
    assert not runtime.calls


@pytest.mark.parametrize(
    "message,code",
    [
        ("No frontal face detected. Use a clear, upright photo with one face.", "FACE_NOT_FOUND"),
        ("Multiple faces detected. Use a photo containing only one face.", "MULTIPLE_FACES"),
        ("Face is too close to the image boundary.", "FACE_OUT_OF_BOUNDS"),
    ],
)
def test_face_rejections_keep_actionable_error_codes(setup, message, code):
    client, runtime, _, _ = setup
    runtime.failure = ValueError(message)
    response = client.post(
        "/analyze", content=b"jpeg", headers={**AUTH, "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 422 and response.json()["code"] == code


def test_internal_failure_does_not_expose_server_paths(setup):
    client, runtime, _, _ = setup
    runtime.failure = RuntimeError("private checkpoint path")
    response = client.post(
        "/analyze", content=b"jpeg", headers={**AUTH, "Content-Type": "image/jpeg"}
    )
    assert response.status_code == 500
    assert "private checkpoint" not in response.text


def test_busy_gpu_is_rejected_without_queueing_images(setup):
    client, runtime, _, _ = setup
    started, release = threading.Event(), threading.Event()

    def slow(raw):
        started.set()
        assert release.wait(5)
        return result()

    runtime.analyze = slow
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post, "/analyze", content=b"jpeg", headers={**AUTH, "Content-Type": "image/jpeg"}
        )
        assert started.wait(5)
        try:
            busy = client.post(
                "/analyze", content=b"jpeg", headers={**AUTH, "Content-Type": "image/jpeg"}
            )
            assert busy.status_code == 503
            assert busy.json()["code"] == "SERVER_BUSY"
            assert busy.headers["retry-after"] == "1"
            assert client.get("/health", headers=AUTH).status_code == 200
        finally:
            release.set()
        assert future.result().status_code == 200


def test_startup_failure_prevents_ready_server():
    factory = Mock(side_effect=RuntimeError("CUDA unavailable"))
    app = api.create_app(
        api.Settings(
            supabase_url="https://test.supabase.co",
            supabase_publishable_key="test-public",
            gpu_uuid="GPU-test",
        ),
        runtime_factory=factory,
    )
    with pytest.raises(RuntimeError, match="CUDA unavailable"), TestClient(app):
        pass


@pytest.mark.parametrize(
    "url,key",
    [("", "public"), ("http://test.supabase.co", "public"), ("https://test.supabase.co", "")],
)
def test_startup_rejects_missing_or_invalid_auth(url, key):
    with pytest.raises(ValueError, match="SUPABASE"):
        api.Settings(supabase_url=url, supabase_publishable_key=key, gpu_uuid="GPU-test")


def test_image_validation_checks_encoded_bytes_before_analysis():
    analyzer = Mock()
    analyzer.analyze.return_value = result()
    runtime = api.GpuRuntime(analyzer, "test")
    with pytest.raises(UnidentifiedImageError):
        runtime.analyze(b"not-an-image")
    analyzer.analyze.assert_not_called()
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="JPEG")
    runtime.analyze(buffer.getvalue())
    analyzer.analyze.assert_called_once_with(buffer.getvalue())


@pytest.mark.parametrize(
    "faces,message", [(None, "No frontal face"), (np.zeros((2, 15)), "Multiple faces")]
)
def test_yunet_rejects_missing_or_multiple_faces(faces, message):
    regions = YuNetRegions.__new__(YuNetRegions)
    regions.detector = Mock()
    regions.detector.detect.return_value = (1, faces)
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400)).save(buffer, format="PNG")
    with pytest.raises(ValueError, match=message):
        regions(buffer.getvalue())


def test_yunet_uses_existing_roi_proportions_and_records_new_method():
    regions = YuNetRegions.__new__(YuNetRegions)
    regions.detector = Mock()
    regions.detector.detect.return_value = (1, np.array([[50, 50, 200, 250, *([0] * 11)]]))
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400)).save(buffer, format="PNG")
    actual = regions(buffer.getvalue())
    assert actual["method"] == ROI_METHOD
    assert actual["boxes"][0] == [0, 0, 400, 400]
    assert actual["boxes"][5] == [66, 170, 122, 232]
    assert actual["training_annotation_match"] is False
