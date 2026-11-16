from fastapi import APIRouter, Depends, Request

from app.core.auth import ChatPrincipal, chat_principal
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter, get_rate_limiter
from app.services.transcription_service import TranscriptionService
from app.services.voice_session_service import VoiceOffer, create_voice_session

router = APIRouter(prefix="/api/chat", tags=["chat"])
MAX_RECORDING_BYTES = 1024 * 1024


@router.post("/ar-control/voice-session")
async def voice_session(
    body: VoiceOffer,
    principal: ChatPrincipal = Depends(chat_principal),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    if not await limiter.allow("ar-voice-session:" + principal.rate_limit_key):
        raise ApiError(429, "Too many voice sessions", "rate_limited")
    return {"sdp": await create_voice_session(body)}


@router.post("/ar-control/transcribe")
async def transcribe(
    request: Request,
    principal: ChatPrincipal = Depends(chat_principal),
    limiter: RateLimiter = Depends(get_rate_limiter),
    service: TranscriptionService = Depends(),
) -> dict[str, str]:
    if not await limiter.allow("ar-voice:" + principal.rate_limit_key):
        raise ApiError(429, "Too many recordings", "rate_limited")
    recording = bytearray()
    async for chunk in request.stream():
        if len(recording) + len(chunk) > MAX_RECORDING_BYTES:
            raise ApiError(413, "Recording is too large", "stt_too_large")
        recording.extend(chunk)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return {"text": await service.transcribe(bytes(recording), media_type)}
