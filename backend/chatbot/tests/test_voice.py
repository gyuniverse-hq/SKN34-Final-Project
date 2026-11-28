import base64
import io
import json
import wave
from email import message_from_bytes
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import httpx
import pytest

from app.clients.transcription_client import TranscriptionClient
from app.core.config import Settings
from app.routers.voice import MAX_RECORDING_BYTES
from app.services.transcription_service import AR_TRANSCRIPTION_PROMPTS

URL = "/api/chat/ar-control/transcribe"
HEADERS = {
    "X-Vishue-Anonymous-Id": "guest-recording-test-0123456789-abcd",
    "Content-Type": "audio/mp4",
}
CONTEXT_HEADER = "X-Vishue-Transcription-Context"


def test_transcribes_one_guest_recording(client):
    provider = AsyncMock()
    provider.transcribe.return_value = "차분한 립 발라줘"
    client.app.dependency_overrides[TranscriptionClient] = lambda: provider
    audio = b"\x00\x00\x00\x18ftypM4A "
    response = client.post(URL, content=audio, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"text": "차분한 립 발라줘"}
    provider.transcribe.assert_awaited_once_with(
        audio, "m4a", "audio/mp4", language="ko", keywords=[], prompt=AR_TRANSCRIPTION_PROMPTS["ko"]
    )


def test_file_transcription_sends_ar_prompt_language_and_repeated_keywords(client, monkeypatch):
    audio = b"\x00\x00\x00\x18ftypM4A "
    settings = Settings(
        stt_model="gpt-transcribe", llm_api_key="test", llm_base_url="https://example.test/v1"
    )
    monkeypatch.setattr("app.clients.transcription_client.get_settings", lambda: settings)
    recorded_parts = {}

    def respond(request):
        assert request.url.path == "/v1/audio/transcriptions"
        form = message_from_bytes(
            b"Content-Type: "
            + request.headers["Content-Type"].encode()
            + b"\r\n\r\n"
            + request.content
        )
        for part in form.get_payload():
            key = part.get_param("name", header="Content-Disposition")
            recorded_parts.setdefault(key, []).append(part.get_payload(decode=True))
        return httpx.Response(200, json={"text": "Use the rose shade"})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    terms = ["롬앤", "Vintage Taupe"]
    context = quote(json.dumps({"language": "en", "keywords": terms}, ensure_ascii=False))
    response = client.post(URL, content=audio, headers={**HEADERS, CONTEXT_HEADER: context})
    assert response.json() == {"text": "Use the rose shade"}
    assert recorded_parts == {
        "file": [audio],
        "model": [b"gpt-transcribe"],
        "languages[]": [b"en"],
        "prompt": [AR_TRANSCRIPTION_PROMPTS["en"].encode()],
        "keywords[]": [term.encode() for term in terms],
    }


@pytest.mark.parametrize(
    "context",
    [{"language": "unknown"}, {"keywords": ["<제품>"]}, {"keywords": ["shade"] * 25}],
)
def test_rejects_invalid_transcription_context_before_provider(client, context):
    provider = AsyncMock()
    client.app.dependency_overrides[TranscriptionClient] = lambda: provider
    response = client.post(
        URL,
        content=b"\x00\x00\x00\x18ftypM4A ",
        headers={**HEADERS, CONTEXT_HEADER: quote(json.dumps(context, ensure_ascii=False))},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "stt_invalid_context"
    provider.transcribe.assert_not_awaited()


@pytest.mark.parametrize(
    ("audio", "status"),
    [(b"", 415), (b"not audio", 415), (b"a" * (MAX_RECORDING_BYTES + 1), 413)],
    ids=["empty", "invalid", "oversize"],
)
def test_rejects_invalid_audio_before_provider(client, audio, status):
    provider = AsyncMock()
    client.app.dependency_overrides[TranscriptionClient] = lambda: provider
    assert client.post(URL, headers=HEADERS, content=audio).status_code == status
    provider.transcribe.assert_not_awaited()


def test_live_model_converts_recording_and_uses_only_the_final_transcript(client, monkeypatch):
    path = "app.clients.transcription_client"
    settings = Settings(
        stt_model="gpt-live-transcribe", llm_api_key="test", llm_base_url="https://example.test/v1"
    )
    monkeypatch.setattr(f"{path}.get_settings", lambda: settings)
    socket = AsyncMock()
    socket.recv.side_effect = [
        '{"type":"session.updated"}',
        '{"type":"conversation.item.input_audio_transcription.delta","delta":"립"}',
        '{"type":"conversation.item.input_audio_transcription.completed","transcript":"립 발라줘"}',
    ]
    connector = MagicMock()
    connector.return_value.__aenter__.return_value = socket
    monkeypatch.setattr(f"{path}.connect", connector)
    recording = io.BytesIO()
    with wave.open(recording, "wb") as wav:
        wav.setparams((2, 2, 48000, 0, "NONE", ""))
        wav.writeframes(bytes(48000 * 2 * 2))
    context = quote(json.dumps({"language": "zh", "keywords": ["粉色"]}, ensure_ascii=False))
    response = client.post(
        URL,
        headers={**HEADERS, "Content-Type": "audio/wav", CONTEXT_HEADER: context},
        content=recording.getvalue(),
    )
    assert response.status_code == 200
    assert response.json() == {"text": "립 발라줘"}
    assert connector.call_args.args == ("wss://example.test/v1/realtime?intent=transcription",)
    update, *audio, commit = [json.loads(call.args[0]) for call in socket.send.await_args_list]
    config = update["session"]["audio"]["input"]
    assert config["transcription"] == {
        "model": "gpt-live-transcribe",
        "languages": ["zh"],
        "prompt": AR_TRANSCRIPTION_PROMPTS["zh"],
        "keywords": ["粉色"],
    }
    assert config["turn_detection"] is None
    assert all(event["type"] == "input_audio_buffer.append" for event in audio)
    assert sum(len(base64.b64decode(event["audio"])) for event in audio) == 24000 * 2
    assert commit == {"type": "input_audio_buffer.commit"}


@pytest.mark.parametrize("model", ["gpt-realtime-2.1-mini", "gpt-live-1"])
def test_voice_offer_uses_only_current_screen_tools_and_rejects_video(client, monkeypatch, model):
    provider = AsyncMock(return_value="v=0\r\n")
    monkeypatch.setattr("app.services.voice_session_service.exchange_offer", provider)
    offer = {
        "model": model,
        "sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n",
        "screen": {"choices": ["get_state/lip"], "summary": "no lipstick applied"},
    }
    url = "/api/chat/ar-control/voice-session"
    headers = {"X-Vishue-Anonymous-Id": HEADERS["X-Vishue-Anonymous-Id"]}
    bad = client.post(
        url, json={**offer, "sdp": offer["sdp"] + "m=video 9 RTP/AVP 96\r\n"}, headers=headers
    )
    assert bad.status_code == 400
    provider.assert_not_awaited()
    assert client.post(url, json=offer, headers=headers).status_code == 200
    session = provider.await_args.args[1]
    engine = session if model.startswith("gpt-realtime") else session["delegation"]["responses"]
    assert engine["tools"][0]["parameters"]["properties"]["choice"]["enum"] == ["get_state/lip"]
    assert ("delegation" in session) == (model == "gpt-live-1")
