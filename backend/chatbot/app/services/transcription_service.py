from fastapi import Depends

from app.clients.transcription_client import TranscriptionClient
from app.core.errors import ApiError


class TranscriptionService:
    def __init__(self, client: TranscriptionClient = Depends()):
        self.client = client

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        if media_type == "audio/mp4" and audio[4:8] == b"ftyp":
            return await self.client.transcribe(audio, "m4a", media_type)
        if media_type == "audio/wav" and audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
            return await self.client.transcribe(audio, "wav", media_type)
        raise ApiError(415, "Expected a microphone recording", "stt_invalid_audio")
