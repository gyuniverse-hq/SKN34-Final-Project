import asyncio

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError

# Busy (503) and rate-limited (429) answers are usually brief; ask again a few times.
RETRY_STATUS = (429, 503)

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiClient:
    """Gemini video understanding for the recipe batch. The only place the Gemini key is used.

    It sends a public YouTube URL and a prompt. No face video or image from a user ever goes
    through here.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delays: tuple[float, ...] = (10, 30, 60),
    ) -> None:
        self._key = api_key
        self.model = model
        self._timeout = timeout
        self._transport = transport
        self._retry_delays = retry_delays

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def generate_json(self, video_url: str, prompt: str, schema: dict) -> str:
        """Ask for JSON that follows ``schema`` about the video; return the model's JSON text."""
        if not self._key:
            raise UpstreamError("Gemini key is not set")
        body = {
            "contents": [
                {"parts": [{"fileData": {"fileUri": video_url}}, {"text": prompt}]},
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.2,
            },
        }
        res = None
        for delay in (*self._retry_delays, None):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    res = await client.post(
                        GENERATE_URL.format(model=self.model),
                        headers={"x-goog-api-key": self._key},
                        json=body,
                    )
            except httpx.HTTPError as exc:
                raise UpstreamError("Gemini request failed") from exc
            if res.status_code not in RETRY_STATUS or delay is None:
                break
            await asyncio.sleep(delay)
        if res is None or res.status_code != 200:
            raise UpstreamError(f"Gemini request failed ({res.status_code if res else '-'})")
        try:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise UpstreamError("Gemini answered unexpectedly") from exc


def get_gemini_client() -> GeminiClient:
    settings = get_settings()
    return GeminiClient(settings.gemini_api_key, settings.gemini_model)
