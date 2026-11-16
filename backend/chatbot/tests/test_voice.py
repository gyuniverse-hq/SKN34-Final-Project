import base64
import io
import json
import wave
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clients.transcription_client import TranscriptionClient
from app.core.config import Settings
from app.routers.voice import MAX_RECORDING_BYTES

URL = "/api/chat/ar-control/transcribe"
HEADERS = {
    "X-Vishue-Anonymous-Id": "guest-recording-test-0123456789-abcd",
    "Content-Type": "audio/mp4",
}


def test_transcribes_one_guest_recording(client):
    provider = AsyncMock()
    provider.transcribe.return_value = "차분한 립 발라줘"
    client.app.dependency_overrides[TranscriptionClient] = lambda: provider
    audio = b"\x00\x00\x00\x18ftypM4A "
    response = client.post(URL, content=audio, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"text": "차분한 립 발라줘"}
    provider.transcribe.assert_awaited_once_with(audio, "m4a", "audio/mp4")


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
    response = client.post(
        URL, headers={**HEADERS, "Content-Type": "audio/wav"}, content=recording.getvalue()
    )
    assert response.status_code == 200
    assert response.json() == {"text": "립 발라줘"}
    assert connector.call_args.args == ("wss://example.test/v1/realtime?intent=transcription",)
    update, *audio, commit = [json.loads(call.args[0]) for call in socket.send.await_args_list]
    config = update["session"]["audio"]["input"]
    assert config["transcription"] == {"model": "gpt-live-transcribe", "languages": ["ko"]}
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
