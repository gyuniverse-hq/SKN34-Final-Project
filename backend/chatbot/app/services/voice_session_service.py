from typing import Literal

from pydantic import BaseModel, Field

from app.clients.voice_session_client import exchange_offer
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.ar_tool import ar_control_tool
from app.schemas.chat import ArControlScreen
from app.services.ar_control_service import GUIDE


class VoiceOffer(BaseModel):
    model: Literal["gpt-realtime-2.1-mini", "gpt-live-1"]
    sdp: str = Field(min_length=10, max_length=32000)
    screen: ArControlScreen


def session_config(model: str, screen: ArControlScreen) -> dict:
    tool = {"type": "function", **ar_control_tool(screen.choices)}
    instructions = (
        GUIDE + "\nAnswer briefly in polite Korean. For an action, wait for its tool result "
        "before speaking. Describe only the confirmed outcome. Screen data:\n" + screen.summary
    )
    if model == "gpt-realtime-2.1-mini":
        return {
            "type": "realtime",
            "model": model,
            "instructions": instructions,
            "tools": [tool],
            "output_modalities": ["audio"],
        }
    return {
        "model": model,
        "instructions": "You are Luna, a Korean makeup artist. Listen to the complete request. "
        "For AR requests generate <|SpawnThinking|> and convey the user's actual request "
        "to the backend. Speak briefly in Korean after the verified result.",
        "delegation": {
            "type": "responses",
            "responses": {
                "model": "gpt-6-luna",
                "reasoning": {"effort": "none"},
                "instructions": instructions,
                "tools": [{**tool, "strict": False}],
                "parallel_tool_calls": False,
            },
        },
        "client": {
            "data_channel": {
                "allowed_client_events": ["response.item.create", "response.create"],
                "allowed_server_events": [
                    {"type": "response.event", "response_event": "response.output_item.done"},
                    {"type": "session.started"},
                    {"type": "error"},
                    {"type": "session.closed"},
                ],
            }
        },
    }


async def create_voice_session(offer: VoiceOffer) -> str:
    if get_settings().env != "local":
        raise ApiError(404, "Comparison only available in local development", "not_found")
    if not offer.sdp.startswith("v=0") or "m=video" in offer.sdp or "m=audio " not in offer.sdp:
        raise ApiError(400, "Expected an audio-only offer", "invalid_request")
    return await exchange_offer(offer.sdp, session_config(offer.model, offer.screen))
