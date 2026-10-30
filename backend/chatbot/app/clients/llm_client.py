from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError


class LlmClient:
    """OpenAI-compatible Chat Completions. The only place the LLM API key is used."""

    def __init__(self, base_url: str, api_key: str | None, model: str | None, timeout: float):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._model)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self._model, "messages": messages}
        if self._model != "gpt-6-luna":
            payload["temperature"] = 0.3
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.post(self._url, json=payload, headers=headers)
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise UpstreamError("LLM request failed") from exc


@lru_cache
def get_llm_client() -> LlmClient:
    s = get_settings()
    return LlmClient(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_seconds)
