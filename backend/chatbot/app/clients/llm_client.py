from functools import lru_cache
from time import perf_counter

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.ar_tool import ar_control_tool


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

    async def choose_ar_control(self, messages: list[dict[str, str]], choices: list[str]) -> dict:
        tool = {"type": "function", "function": ar_control_tool(choices)}
        tool["function"]["parameters"]["properties"]["onAppliedReply"] = {
            "type": "string",
            "description": (
                "For relative intensity changes only (up, down, half), write one short, warm "
                "makeup-artist sentence in the user's language for the confirmed change. "
                "Describe how the softer or bolder color feels; a brief invitation for their "
                "opinion is welcome. In swatches_only describe the shade. Avoid slider jargon, "
                "steps, numbers, invented products or observations about the person's face. "
                "Omit for other choices or if further result details are needed."
            ),
        }
        options = {"reasoning_effort": "none"} if self._model == "gpt-6-luna" else {}
        response = await self._request(messages, tools=[tool], tool_choice="auto", **options)
        calls = response.get("tool_calls", [])
        if not calls:
            return {"answer": response.get("content", "")}
        if len(calls) != 1 or calls[0]["function"]["name"] != "ar_control":
            raise UpstreamError("Unexpected AR tool call")
        return {"arguments": calls[0]["function"]["arguments"]}

    async def complete(self, messages: list[dict[str, str]], *, ar_feedback: bool = False) -> str:
        options = (
            {"reasoning_effort": "none"} if ar_feedback and self._model == "gpt-6-luna" else {}
        )
        response = await self._request(messages, **options)
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise UpstreamError("Empty LLM response")
        return content.strip()

    async def _request(self, messages: list[dict[str, str]], **options) -> dict:
        payload = {"model": self._model, "messages": messages, **options}
        if self._model != "gpt-6-luna":
            payload["temperature"] = 0.3
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.post(self._url, json=payload, headers=headers)
            res.raise_for_status()
            return res.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise UpstreamError("LLM request failed") from exc

    async def complete_with_tools(
        self, messages, tools, *, required_tool=None
    ) -> tuple[dict, float]:
        payload = {
            "model": self._model,
            "messages": messages,
            "store": False,
        }
        if tools:
            payload["tools"] = tools
            payload["parallel_tool_calls"] = False
        if self._model == "gpt-6-luna":
            # This model accepts Chat Completions function tools with reasoning disabled.
            payload["reasoning_effort"] = "none"
        if required_tool:
            payload["tool_choice"] = {"type": "function", "function": {"name": required_tool}}
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid completion response")
            return result, round((perf_counter() - started) * 1000, 1)
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError("G1 LLM request failed") from exc


@lru_cache
def get_llm_client() -> LlmClient:
    s = get_settings()
    return LlmClient(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_timeout_seconds)


@lru_cache
def get_ar_llm_client() -> LlmClient:
    return get_llm_client()
