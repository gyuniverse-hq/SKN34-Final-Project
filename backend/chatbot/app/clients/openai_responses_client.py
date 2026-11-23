"""Strict Responses API transport for the versioned knowledge stages."""

import asyncio
import json
from dataclasses import dataclass
from time import perf_counter

import httpx

from app.core.errors import UpstreamError

MODEL = "gpt-6.1-terra"


@dataclass(frozen=True)
class StageResult:
    content: dict
    usage: dict
    elapsed_ms: int
    attempts: int
    request_id: str | None

    def metrics(self):
        usage = self.usage
        inputs = usage["input_tokens"]
        detail = usage.get("input_tokens_details") or {}
        cached = detail.get("cached_tokens", 0)
        writes = detail.get("cache_write_tokens", 0)
        outputs = usage["output_tokens"]
        # Standard short-context rate for the version fixed in this experiment.
        usd = (inputs - cached - writes + 0.05 * cached + 1.25 * writes + 5 * outputs) / 1e6
        return {
            "inputTokens": inputs,
            "cachedTokens": cached,
            "outputTokens": outputs,
            "estimatedUsd": usd,
            "elapsedMs": self.elapsed_ms,
            "attempts": self.attempts,
            "requestId": self.request_id,
        }


class OpenAIResponses:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def run(self, stage, prompt, value, schema, max_tokens):
        start = perf_counter()
        payload = {
            "model": MODEL,
            "store": False,
            "stream": False,
            "service_tier": "default",
            "reasoning": {"effort": "none"},
            "instructions": prompt,
            "input": json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": f"g5_{stage}",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        for attempt in range(1, 3):
            try:
                response = await self.http.post("responses", json=payload)
                response.raise_for_status()
                data = response.json()
                if data["status"] != "completed":
                    raise ValueError("Incomplete knowledge response")
                pieces = [
                    item["text"]
                    for out in data["output"]
                    if out["type"] == "message"
                    for item in out["content"]
                    if item["type"] == "output_text"
                ]
                if len(pieces) != 1:
                    raise ValueError("No structured knowledge response")
                return StageResult(
                    json.loads(pieces[0]),
                    data["usage"],
                    round((perf_counter() - start) * 1000),
                    attempt,
                    response.headers.get("x-request-id"),
                )
            except httpx.HTTPStatusError as exc:
                if attempt >= 2 or exc.response.status_code not in (408, 429, 500, 502, 503, 504):
                    raise UpstreamError("Knowledge model request failed") from exc
            except httpx.TransportError as exc:
                if attempt >= 2:
                    raise UpstreamError("Knowledge model unreachable") from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise UpstreamError("Invalid knowledge model response") from exc
            await asyncio.sleep(1)
        raise AssertionError("Unreachable knowledge retry state")
