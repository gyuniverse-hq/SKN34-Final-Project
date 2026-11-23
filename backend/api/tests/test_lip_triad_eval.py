import io
import json

import anyio
import httpx
import pytest
from PIL import Image

from app.clients.vision_llm_client import VisionLlmClient
from app.core.errors import ApiError
from app.services.lip_technical_metrics import score_triad
from app.services.lip_triad_eval_service import LipTriadEvalService


def _png(color, size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_technical_scores_close_images_as_passish():
    bare = _png((180, 120, 120))
    real = _png((200, 80, 100))
    ar = _png((198, 82, 102))
    out = score_triad(bare, real, ar)
    assert out["criteriaVersion"] == "technical-admin-v1.0"
    assert out["items"]["delta_e"]["value"] < out["items"]["delta_e"]["bareValue"]
    assert out["items"]["ssim"]["value"] > 0.9
    assert out["items"]["mae"]["value"] < 0.05
    assert 0 <= out["items"]["miou"]["value"] <= 1
    assert out["items"]["lpips"]["verdict"] == "report_only"


def test_technical_rejects_huge_payload():
    with pytest.raises(ValueError, match="too large"):
        score_triad(b"x" * (8 * 1024 * 1024 + 1), _png((0, 0, 0)), _png((0, 0, 0)))


def test_vision_parse_and_mean():
    client = VisionLlmClient("https://example.test/v1", "k", "gpt-test", 5)
    parsed = client._parse(
        json.dumps(
            {
                "delta_e": 4,
                "ssim": 5,
                "mae": 3,
                "miou": 4,
                "lpips": 4,
                "brief_reason": "색과 윤곽이 가깝다",
            }
        )
    )
    assert parsed["mean"] == 4.0
    assert parsed["scores"]["ssim"] == 5


def test_vision_score_naturalness_posts_images(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "delta_e": 5,
                                    "ssim": 4,
                                    "mae": 4,
                                    "miou": 5,
                                    "lpips": 4,
                                    "brief_reason": "ok",
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            calls.append((url, json, headers))
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = VisionLlmClient("https://api.openai.com/v1", "secret", "astra-x", 10)
    result = anyio.run(client.score_naturalness, _png((1, 2, 3)), _png((4, 5, 6)))
    assert result["scores"]["delta_e"] == 5
    assert calls and "image_url" in str(calls[0][1])
    assert "secret" in calls[0][2]["Authorization"]


def test_service_keeps_no_image_bytes_in_audit():
    audits = []

    class FakeRepo:
        def transaction(self):
            class Ctx:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return None

            return Ctx()

        def audit(self, actor, action, target_type, target_id, before, after, request_id):
            audits.append(after)

    class FakeVision:
        async def score_naturalness(self, *a, **k):
            return {
                "criteriaVersion": "naturalness-techlang-v1.0",
                "scores": {"delta_e": 4, "ssim": 4, "mae": 4, "miou": 4, "lpips": 4},
                "mean": 4.0,
                "briefReason": "비슷함",
                "model": "astra-x",
            }

    class Upload:
        def __init__(self, data, name, ctype):
            self._data = data
            self.filename = name
            self.content_type = ctype

        async def read(self):
            return self._data

    service = LipTriadEvalService(FakeRepo(), FakeVision())
    out = anyio.run(
        service.evaluate,
        Upload(_png((10, 10, 10)), "bare.png", "image/png"),
        Upload(_png((200, 40, 80)), "real.png", "image/png"),
        Upload(_png((190, 50, 70)), "ar.png", "image/png"),
        "user-1",
    )
    assert out["retainedImages"] is False
    blob = json.dumps(audits[0])
    assert "PNG" not in blob
    assert audits[0]["technicalOverall"] in ("pass", "fail", "report_only")
    assert "naturalnessMean" in audits[0]


def test_unconfigured_vision_raises():
    client = VisionLlmClient("https://api.openai.com/v1", None, None, 5)
    with pytest.raises(ApiError) as exc:
        anyio.run(client.score_naturalness, _png((1, 1, 1)), _png((2, 2, 2)))
    assert exc.value.code == "astra_unavailable"
