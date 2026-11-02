from __future__ import annotations

import base64
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


class OpenAIJudge:
    def __init__(self, config: dict, env_path: Path | None = None):
        env = dotenv_values(env_path) if env_path and env_path.exists() else {}
        # Explicit environment values take precedence; validate before any network or SDK client.
        if os.environ.get('ALLOW_EXTERNAL_JUDGE', env.get('ALLOW_EXTERNAL_JUDGE')) != 'true':
            raise RuntimeError('ALLOW_EXTERNAL_JUDGE=true is required before external calls')
        key = os.environ.get('OPENAI_API_KEY', env.get('OPENAI_API_KEY'))
        if not key:
            raise RuntimeError('OPENAI_API_KEY is required')
        from openai import AsyncOpenAI

        self._config = config
        # The pipeline handles retries and timeout accounting; disable SDK retries.
        self._client = AsyncOpenAI(api_key=key, timeout=config['timeout_s'], max_retries=0)

    async def verify_model(self) -> None:
        names = sorted([model.id async for model in self._client.models.list()])
        model = self._config.get('model', '')
        if not model or model not in names:
            raise ValueError('Set judges.json model to an available model. Available: ' + ', '.join(names))

    async def judge(self, prompt: str, images: list[tuple[str, bytes]], schema: type[BaseModel]) -> JudgeResult:
        content = [{'type': 'input_text', 'text': prompt}]
        for label, data in images:
            encoded = base64.b64encode(data).decode('ascii')
            content.extend([{'type': 'input_text', 'text': label},
                            {'type': 'input_image', 'image_url': f'data:image/jpeg;base64,{encoded}', 'detail': 'high'}])
        params = {'model': self._config['model'], 'input': [{'role': 'user', 'content': content}],
                  'text_format': schema, 'store': False}
        if self._config.get('temperature') is not None:
            params['temperature'] = self._config['temperature']
        response = await self._client.responses.parse(**params)
        if response.output_parsed is None:
            # Empty, incomplete and refusal responses must not become successful judgments.
            raise ValueError('OpenAI returned no structured response')
        parsed = schema.model_validate(response.output_parsed)
        usage = response.usage
        return JudgeResult(parsed.model_dump(), getattr(usage, 'input_tokens', None),
                           getattr(usage, 'output_tokens', None))
