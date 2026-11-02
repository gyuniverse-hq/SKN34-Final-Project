from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values
from pydantic import BaseModel


@dataclass
class JudgeResult:
    value: dict
    input_tokens: int | None = None
    output_tokens: int | None = None


class JudgeClient(Protocol):
    async def judge(self, prompt: str, images: list[tuple[str, bytes]], schema: type[BaseModel]) -> JudgeResult: ...


class GeminiJudge:
    def __init__(self, config: dict, env_path: Path | None = None):
        env = dotenv_values(env_path) if env_path and env_path.exists() else {}
        # Explicit environment values take precedence; validate before any network or SDK client.
        if os.environ.get('ALLOW_EXTERNAL_JUDGE', env.get('ALLOW_EXTERNAL_JUDGE')) != 'true':
            raise RuntimeError('ALLOW_EXTERNAL_JUDGE=true is required before external calls')
        key = os.environ.get('GEMINI_API_KEY', env.get('GEMINI_API_KEY'))
        if not key:
            raise RuntimeError('GEMINI_API_KEY is required')
        from google import genai
        from google.genai import types

        self._types = types
        self._config = config
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(config['timeout_s'] * 1000)))

    async def verify_model(self) -> None:
        models = await asyncio.to_thread(lambda: list(self._client.models.list()))
        names = sorted(m.name.removeprefix('models/') for m in models if m.name)
        model = self._config.get('model', '').removeprefix('models/')
        if not model or model not in names:
            raise ValueError('Set judges.json model to an available model. Available: ' + ', '.join(names))

    async def judge(self, prompt: str, images: list[tuple[str, bytes]], schema: type[BaseModel]) -> JudgeResult:
        content = [prompt]
        for label, data in images:
            content.extend([label, self._types.Part.from_bytes(data=data, mime_type='image/jpeg')])
        response = await self._client.aio.models.generate_content(
            model=self._config['model'], contents=content,
            config=self._types.GenerateContentConfig(temperature=self._config['temperature'],
                response_mime_type='application/json', response_schema=schema))
        parsed = schema.model_validate_json(response.text or '')
        usage = response.usage_metadata
        return JudgeResult(parsed.model_dump(), getattr(usage, 'prompt_token_count', None),
                           getattr(usage, 'candidates_token_count', None))
