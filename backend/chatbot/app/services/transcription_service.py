from fastapi import Depends

from app.clients.transcription_client import TranscriptionClient
from app.core.errors import ApiError
from app.schemas.chat import Locale
from app.schemas.voice import ArTranscriptionContext

AR_TRANSCRIPTION_PROMPTS: dict[Locale, str] = {
    "ko": "AR 메이크업 체험 중인 대화입니다. 화장품 브랜드명, 제품명, 호수명이 나옵니다.",
    "en": "An AR makeup try-on conversation with cosmetic brands, product names and shade names.",
    "ja": "ARでメイクを試す会話です。化粧品のブランド名、商品名、色名が出てきます。",
    "zh": "一段 AR 美妆试妆对话，涉及化妆品品牌名、产品名和色号名。",
}


class TranscriptionService:
    def __init__(self, client: TranscriptionClient = Depends()):
        self.client = client

    async def transcribe(
        self, audio: bytes, media_type: str, context: ArTranscriptionContext
    ) -> str:
        if media_type == "audio/mp4" and audio[4:8] == b"ftyp":
            extension = "m4a"
        elif media_type == "audio/wav" and audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
            extension = "wav"
        else:
            raise ApiError(415, "Expected a microphone recording", "stt_invalid_audio")
        return await self.client.transcribe(
            audio,
            extension,
            media_type,
            language=context.language,
            prompt=AR_TRANSCRIPTION_PROMPTS[context.language],
            keywords=context.keywords,
        )
