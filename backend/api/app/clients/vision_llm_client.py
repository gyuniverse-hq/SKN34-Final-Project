"""OpenAI-compatible vision Chat Completions.

Only place the Astra/LLM API key is used for image scoring.
"""

from __future__ import annotations

import base64
import json
import re
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError

NATURALNESS_VERSION = "naturalness-techlang-v1.0"
SYSTEM_PROMPT = """당신은 립 가상 메이크업 자연스러움 심사자입니다.
실제로 바른 입술 사진과 AR 사진을 비교합니다.

규칙:
- 주어진 이미지만으로 판단하세요.
- 축은 정확히 5개: delta_e, ssim, mae, miou, lpips.
- 각 축은 정수 1~5만. 총평으로 점수를 대신하지 마세요.
- 질문은 모두 긍정형입니다. 점수가 높을수록 더 비슷·더 잘 맞음을 뜻합니다.
- 애매하면 3에 몰지 말고, 보이는 근거로 2 또는 4를 택하세요.
- 명백한 스티커·페인트·영역 이탈에는 엄격하세요.

문항:
- delta_e: AR과 실제로 바른 입술의 색이 얼마나 비슷해 보이는가?
- ssim: 모양·명암·결 느낌이 얼마나 비슷해 보이는가?
- mae: 전체적으로 얼마나 비슷해 보이는가?
- miou: AR 색이 입술 영역·윤곽에 얼마나 잘 맞게 올라가 있는가?
- lpips: 실제로 바른 입술과 얼마나 자연스럽게 비슷해 보이는가?

척도: 1 전혀 아니다 · 2 아니다 · 3 보통 · 4 그렇다 · 5 매우 그렇다

JSON만 출력 (코드블록·추가 키 금지):
{
  "delta_e": 1|2|3|4|5,
  "ssim": 1|2|3|4|5,
  "mae": 1|2|3|4|5,
  "miou": 1|2|3|4|5,
  "lpips": 1|2|3|4|5,
  "brief_reason": "주요 근거 한 줄"
}
"""
SCORE_KEYS = ("delta_e", "ssim", "mae", "miou", "lpips")


class VisionLlmClient:
    def __init__(self, base_url: str, api_key: str | None, model: str | None, timeout: float):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._model)

    def _data_url(self, data: bytes, mime: str) -> str:
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    def _parse(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpstreamError("Astra response was not JSON") from exc
        scores = {}
        for key in SCORE_KEYS:
            value = payload.get(key)
            if not isinstance(value, int) or value < 1 or value > 5:
                raise UpstreamError(f"Astra score invalid: {key}")
            scores[key] = value
        reason = payload.get("brief_reason", "")
        if not isinstance(reason, str):
            reason = ""
        reason = reason.strip()[:200]
        mean = round(sum(scores.values()) / len(scores), 2)
        return {
            "criteriaVersion": NATURALNESS_VERSION,
            "scores": scores,
            "mean": mean,
            "briefReason": reason,
            "model": self._model,
        }

    async def score_naturalness(
        self,
        real_bytes: bytes,
        ar_bytes: bytes,
        *,
        real_mime: str = "image/jpeg",
        ar_mime: str = "image/jpeg",
        bare_bytes: bytes | None = None,
        bare_mime: str = "image/jpeg",
    ) -> dict:
        if not self.configured:
            raise ApiError(503, "Astra / vision LLM is not configured", "astra_unavailable")
        content: list[dict] = [
            {
                "type": "text",
                "text": "실제로 바른 입술 이미지와 AR 이미지를 보고 위 JSON으로만 답하세요.",
            },
            {
                "type": "text",
                "text": "실제로 바른 입술:",
            },
            {
                "type": "image_url",
                "image_url": {"url": self._data_url(real_bytes, real_mime)},
            },
            {
                "type": "text",
                "text": "AR:",
            },
            {
                "type": "image_url",
                "image_url": {"url": self._data_url(ar_bytes, ar_mime)},
            },
        ]
        if bare_bytes:
            content.extend(
                [
                    {"type": "text", "text": "참고용 화장 전(맨입술):"},
                    {
                        "type": "image_url",
                        "image_url": {"url": self._data_url(bare_bytes, bare_mime)},
                    },
                ]
            )
        payload = {
            "model": self._model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.post(self._url, json=payload, headers=headers)
            res.raise_for_status()
            message = res.json()["choices"][0]["message"]["content"]
            return self._parse(message if isinstance(message, str) else str(message))
        except ApiError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, ValueError, UpstreamError) as exc:
            if isinstance(exc, UpstreamError):
                raise ApiError(502, str(exc), "astra_failed") from exc
            raise ApiError(502, "Astra request failed", "astra_failed") from exc


@lru_cache
def get_vision_llm_client() -> VisionLlmClient:
    s = get_settings()
    return VisionLlmClient(
        s.llm_base_url,
        s.llm_api_key,
        s.llm_model or s.astra_model,
        s.llm_timeout_seconds,
    )
