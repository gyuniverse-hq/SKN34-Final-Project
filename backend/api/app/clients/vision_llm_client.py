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

NATURALNESS_VERSION = "naturalness-techlang-v1.1"
SYSTEM_PROMPT = """당신은 립 가상 메이크업 자연스러움 심사자입니다.
실제로 바른 입술 사진과 AR 사진을 비교합니다.

규칙:
- 주어진 이미지만으로 판단하세요.
- 축은 정확히 5개: delta_e, ssim, mae, miou, lpips.
- 각 축은 정수 1~5만. 총평으로 점수를 대신하지 마세요.
- 점수가 높을수록 AR이 실바름에 더 가깝습니다.
- 문항별 1~5 앵커를 따르세요.
- 애매하면 3에 몰지 말고, 보이는 근거로 2 또는 4를 택하세요.
- 명백한 스티커·페인트·영역 이탈에는 엄격하세요.

문항·앵커:
- delta_e (색): AR과 실바름의 색이 얼마나 비슷해 보이는가?
  1 누가 봐도 색이 완전히 다름
  2 색 차이가 크고 한눈에 어긋남
  3 비슷한 계열이지만 밝기·채도·톤이 꽤 다름
  4 대체로 같고 작은 색감 차이만
  5 실제 립 색과 AR 색이 거의 동일
- ssim (모양·명암·결): 모양·명암·결 느낌이 얼마나 비슷해 보이는가?
  1 전혀 다른 입술처럼 보임
  2 형태·명암·결이 크게 어긋남
  3 대체로 비슷하나 일부가 어색
  4 잘 맞고 사소한 차이만
  5 구조·결 느낌이 거의 구분되지 않음
- mae (전체 인상): 전체적으로 얼마나 비슷해 보이는가?
  1 전체 인상이 완전히 다름
  2 전체적으로 크게 달라 보임
  3 비슷하나 어색한 부분이 분명
  4 잘 맞고 작은 이질감만
  5 전체 인상이 거의 같음
- miou (영역·윤곽): AR 색이 입술 영역·윤곽에 잘 맞게 올라가 있는가?
  1 피부·이 등으로 크게 나감
  2 이탈·이중선·큰 번짐
  3 대체로 맞지만 입꼬리·경계 일부 어색
  4 윤곽을 잘 따르고 사소한 흔들림만
  5 영역·윤곽에 정확히 맞음
- lpips (자연스러움): 실바름과 얼마나 자연스럽게 비슷해 보이는가?
  1 스티커·페인트·필터처럼 명백히 다름
  2 합성 티·플라스틱감이 강함
  3 비슷하나 떠 보이거나 부자연스러움
  4 대체로 자연스럽고 작은 어색함만
  5 실바름과 구분하기 어려울 정도

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
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        }
        # Some Astra / OpenAI models only accept the default temperature.
        if self._model not in {"gpt-6-luna", "gpt-6.2-astra"} and not str(self._model).endswith(
            "-astra"
        ):
            payload["temperature"] = 0.2
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
