import json

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError


async def exchange_offer(sdp: str, session: dict) -> str:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ApiError(503, "Voice session unavailable", "voice_unavailable")
    live = session["model"] == "gpt-live-1"
    path = "/live/sessions" if live else "/realtime/calls"
    url = settings.llm_base_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if live:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "session": session,
                        "transport": {"type": "webrtc", "sdp": sdp},
                    },
                )
            else:
                response = await client.post(
                    url,
                    headers=headers,
                    files={
                        "sdp": (None, sdp),
                        "session": (None, json.dumps(session)),
                    },
                )
            response.raise_for_status()
            answer = response.json()["transport"]["sdp"] if live else response.text
            if not answer.startswith("v=0"):
                raise ValueError("Invalid session answer")
            return answer
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise ApiError(502, "Voice session setup failed", "voice_setup_failed") from exc
