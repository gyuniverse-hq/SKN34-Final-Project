import asyncio
import base64
import io
import json
from itertools import chain

import av
import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

PCM_RATE = 24_000


def _decode_pcm(audio: bytes, extension: str) -> bytes:
    """Decode an app recording to mono PCM16 without writing it to disk."""
    pcm = bytearray()
    try:
        with av.open(
            io.BytesIO(audio),
            format="mov" if extension == "m4a" else "wav",
            options={"protocol_whitelist": ""},
        ) as source:
            if not source.streams.audio:
                raise ValueError("Missing audio stream")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=PCM_RATE)
            # Flush the last samples buffered by the resampler at the end of the turn.
            for frame in chain(source.decode(audio=0), (None,)):
                for converted in resampler.resample(frame):
                    pcm.extend(memoryview(converted.planes[0])[: converted.samples * 2])
                    # The app stops at 30 s; allow a little recorder/encoder overhead.
                    if len(pcm) > 32 * PCM_RATE * 2:
                        raise ApiError(413, "Recording is too long", "stt_too_large")
    except (av.FFmpegError, ValueError) as exc:
        raise ApiError(415, "Invalid microphone recording", "stt_invalid_audio") from exc
    if not pcm:
        raise ApiError(422, "No speech recognized", "stt_empty")
    return bytes(pcm)


async def _wait_for_event(socket: ClientConnection, expected: str) -> dict:
    while True:
        event = json.loads(await socket.recv())
        if event["type"] in {"error", "conversation.item.input_audio_transcription.failed"}:
            raise ApiError(502, "Transcription failed", "stt_failed")
        if event["type"] == expected:
            return event


async def _transcribe_live(
    settings: Settings, audio: bytes, extension: str, transcription: dict
) -> str:
    pcm = await asyncio.to_thread(_decode_pcm, audio, extension)
    base = httpx.URL(settings.llm_base_url.rstrip("/") + "/realtime")
    url = base.copy_with(
        scheme="wss" if base.scheme == "https" else "ws", params={"intent": "transcription"}
    )
    async with (
        asyncio.timeout(settings.llm_timeout_seconds),
        connect(
            str(url),
            additional_headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            close_timeout=1,
            compression=None,
        ) as socket,
    ):
        audio_input = {
            "format": {"type": "audio/pcm", "rate": PCM_RATE},
            "transcription": transcription,
            "turn_detection": None,
        }
        await socket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {"type": "transcription", "audio": {"input": audio_input}},
                }
            )
        )
        await _wait_for_event(socket, "session.updated")
        for offset in range(0, len(pcm), PCM_RATE * 2):
            chunk = pcm[offset : offset + PCM_RATE * 2]
            await socket.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode(),
                    }
                )
            )
        await socket.send(json.dumps({"type": "input_audio_buffer.commit"}))
        final = await _wait_for_event(
            socket, "conversation.item.input_audio_transcription.completed"
        )
        return final["transcript"]


class TranscriptionClient:
    async def transcribe(
        self,
        audio: bytes,
        extension: str,
        media_type: str,
        *,
        language: str,
        prompt: str,
        keywords: list[str],
    ) -> str:
        settings = get_settings()
        if not settings.llm_api_key or not settings.stt_model:
            raise ApiError(503, "Transcription is unavailable", "stt_unavailable")
        try:
            if settings.stt_model == "gpt-live-transcribe":
                transcription = {
                    "model": settings.stt_model,
                    "languages": [language],
                    "prompt": prompt,
                    **({"keywords": keywords} if keywords else {}),
                }
                text = await _transcribe_live(settings, audio, extension, transcription)
            else:
                fields: dict[str, str | list[str]] = {"model": settings.stt_model}
                if settings.stt_model == "gpt-transcribe":
                    fields.update({"languages[]": [language], "prompt": prompt})
                    if keywords:
                        fields["keywords[]"] = keywords
                else:
                    fields["language"] = language
                async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                    response = await client.post(
                        f"{settings.llm_base_url.rstrip('/')}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                        data=fields,
                        files={"file": (f"command.{extension}", audio, media_type)},
                    )
                    response.raise_for_status()
                    text = response.json()["text"]
        except (
            httpx.HTTPError,
            WebSocketException,
            OSError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ApiError(502, "Transcription failed", "stt_failed") from exc
        if not isinstance(text, str) or not text.strip():
            raise ApiError(422, "No speech recognized", "stt_empty")
        return text.strip()
