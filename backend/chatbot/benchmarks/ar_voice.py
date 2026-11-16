"""Replay an M4A into an isolated Chromium tab. Run from the repo root; see the comparison MD."""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from websockets.sync.client import connect

from app.core.config import get_settings
from app.main import app
from app.schemas.chat import ArControlScreen
from app.services.voice_session_service import VoiceOffer, create_voice_session

ROOT = Path(__file__).resolve().parents[3]
SCREEN = ArControlScreen(
    choices=[
        "get_state/lip",
        "adjust_intensity/lip/up",
        "adjust_intensity/lip/down",
        "adjust_intensity/lip/half",
        "clear_layer/lip",
        "apply_shade/blush/by_color",
    ],
    summary=json.dumps(
        {
            "zone": "lip",
            "displayMode": "swatches_only",
            "worn": [
                {"zone": "lip", "product": "Rose", "intensity": 0.55},
            ],
        }
    ),
)


class Page:
    def __init__(self, socket):
        self.socket = socket
        self.seq = 0

    def evaluate(self, expression):
        self.seq += 1
        self.socket.send(
            json.dumps(
                {
                    "id": self.seq,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                }
            )
        )
        while True:
            payload = json.loads(self.socket.recv(timeout=20))
            if payload.get("id") == self.seq:
                result = payload["result"]
                if "exceptionDetails" in result:
                    raise RuntimeError(
                        result["exceptionDetails"]
                        .get("exception", {})
                        .get("description", "Script error")
                    )
                return result["result"].get("value")


# Use the same microphone source and clock for every mode. The local swatch is an observation
# surface; it doesn't simulate the mobile face tracker or its frame acknowledgement.
SETUP = """
document.body.innerHTML='<canvas width="80" height="80"></canvas>';
window.messages=[];
window.ReactNativeWebView={postMessage: raw => messages.push(JSON.parse(raw))};
window.ac=new AudioContext({sampleRate:24000}); await ac.resume();
window.clip=await ac.decodeAudioData(Uint8Array.from(atob(encoded), c=>c.charCodeAt(0)).buffer);
const samples=clip.getChannelData(0);
let end=0;
for(let i=0;i<samples.length;i+=480) {
  let p=0; for(let j=i;j<Math.min(i+480,samples.length);j++) p+=samples[j]*samples[j];
  if(p/480>0.0001) end=Math.min(i+480,samples.length)/clip.sampleRate;
}
if(!end) throw Error('No speech in sample');
window.dest=ac.createMediaStreamDestination();
Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>dest.stream}});
window.play=()=>{const src=ac.createBufferSource(); src.buffer=clip; src.connect(dest);
  const start=ac.currentTime+0.1; window.eos=performance.now()+100+1000*end; src.start(start); };
const canvas=document.querySelector('canvas'), g=canvas.getContext('2d');
function draw(intensity) {g.fillStyle='white';g.fillRect(0,0,80,80);
  g.fillStyle='rgba(170,35,85,'+intensity+')'; g.fillRect(0,0,80,80);}
draw(.55);
window.paint=async()=>{const before=g.getImageData(10,10,1,1).data[1];draw(.45);
  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
  if(before===g.getImageData(10,10,1,1).data[1])throw Error('Swatch unchanged');
  return performance.now()-eos;};
window.speechSynthesis.getVoices();
"""


def trial(page, client, model, audio):
    def js(code):
        return page.evaluate(code)

    bridge = (ROOT / "components/ar/voiceSessionHtml.ts").read_text(encoding="utf-8")
    script = bridge.split("<script>", 1)[1].split("</script>")[0]
    encoded = base64.b64encode(audio).decode()
    js("(async()=>{const encoded=" + json.dumps(encoded) + ";" + SETUP + "})()")
    headers = {"X-Vishue-Anonymous-Id": "ar-voice-lab-" + uuid4().hex}
    outcome = {
        "choice": "adjust_intensity/lip/down",
        "status": "APPLIED",
        "displayMode": "swatches_only",
        "before": 0.55,
        "after": 0.45,
    }
    screen_ms = None
    if model in {"gpt-transcribe", "gpt-live-transcribe"}:
        os.environ["STT_MODEL"] = model
        get_settings.cache_clear()
        js("play()")
        js("new Promise(r=>setTimeout(r,Math.max(0,eos+1200-performance.now())))")
        stt = client.post(
            "/api/chat/ar-control/transcribe",
            content=audio,
            headers={**headers, "Content-Type": "audio/mp4"},
        )
        stt.raise_for_status()
        text = stt.json()["text"]
        request = {
            "requestId": str(uuid4()),
            "locale": "ko",
            "requestType": "ar_command",
            "message": text,
            "arContext": {
                "screenId": "A-01",
                "stateVersion": 1,
                "activeZone": "lip",
                "supportedActions": ["ar_control"],
                "lip": None,
                "control": SCREEN.model_dump(),
            },
        }
        response = client.post("/api/chat", json=request, headers=headers)
        response.raise_for_status()
        proposal = response.json()["arResult"]["actionProposal"]
        if (
            not proposal
            or proposal["choice"] != outcome["choice"]
            or (proposal.get("steps") or 1) != 1
        ):
            raise ValueError("Unexpected action")
        screen_ms = js("paint()")
        answer = proposal.get("onAppliedReply")
        used_prepared_reply = bool(answer)
        if not answer:
            reply = client.post(
                "/api/chat/ar-control/reply",
                headers=headers,
                json={
                    "requestId": request["requestId"],
                    "commandId": proposal["commandId"],
                    "locale": "ko",
                    "message": text,
                    "result": json.dumps(outcome),
                },
            )
            reply.raise_for_status()
            answer = reply.json()["answer"]
        utterance = json.dumps(answer)
        speech_ms = js(
            """new Promise(resolve=>{const s=new SpeechSynthesisUtterance("""
            + utterance
            + """);s.lang='ko-KR';s.onstart=()=>resolve(performance.now()-eos);
                       s.onerror=()=>resolve(null);setTimeout(()=>resolve(null),3500);
                       speechSynthesis.speak(s);})"""
        )
        return {
            "screenMs": screen_ms, "speechMs": speech_ms, "answer": answer,
            "usedPreparedReply": used_prepared_reply,
        }

    js(script)
    js("void startVoice()")
    expires = time.monotonic() + 45
    speech_ms = None
    while time.monotonic() < expires:
        for event in js("messages.splice(0)"):
            kind = event["type"]
            if kind == "offer":
                offer = VoiceOffer(model=model, sdp=event["sdp"], screen=SCREEN)
                answer = asyncio.run(create_voice_session(offer))
                js("setAnswer(" + json.dumps(answer) + ")")
            elif kind == "ready":
                js("play()")
            elif kind == "tool":
                if (
                    event["args"].get("choice") != outcome["choice"]
                    or (event["args"].get("steps") or 1) != 1
                ):
                    raise ValueError("Unexpected tool arguments: " + str(event["args"]))
                screen_ms = js("paint()")
                js("toolResult(" + json.dumps(outcome) + ")")
            elif kind == "speaking":
                speech_ms = js("firstAudio-eos")
            elif kind == "failed":
                raise RuntimeError("WebRTC session failed")
        if screen_ms is not None and speech_ms is not None:
            return {"screenMs": screen_ms, "speechMs": speech_ms}
        time.sleep(0.02)
    return {
        "screenMs": screen_ms,
        "speechMs": speech_ms,
        "error": "timeout",
        "state": js(
            "({ready, inputDetected:lastVoice!=null, connected:pc?.connectionState,"
            "audioContext:ctx?.state, player:document.querySelector('audio')?.currentTime})"
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("m4a", type=Path)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--models",
        nargs="+",
        default=[
            "gpt-transcribe",
            "gpt-realtime-2.1-mini",
            "gpt-live-transcribe",
            "gpt-live-1",
        ],
    )
    args = parser.parse_args()
    audio = args.m4a.read_bytes()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile, TestClient(app) as c:
        browser = subprocess.Popen(
            [
                args.browser,
                "--headless=new",
                "--remote-debugging-port=0",
                "--user-data-dir=" + profile,
                "--no-first-run",
                "--no-default-browser-check",
                "--autoplay-policy=no-user-gesture-required",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            portfile = Path(profile) / "DevToolsActivePort"
            for _ in range(150):
                if portfile.exists():
                    break
                time.sleep(0.1)
            port = portfile.read_text().splitlines()[0]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as debugger:
                for i in range(args.runs):
                    for model in (
                        args.models[i % len(args.models) :] + args.models[: i % len(args.models)]
                    ):
                        tab = debugger.put("/json/new?about:blank").json()
                        try:
                            with connect(tab["webSocketDebuggerUrl"], proxy=None) as socket:
                                result = trial(Page(socket), c, model, audio)
                        except Exception as exc:
                            result = {"error": str(exc)}
                            cause = exc.__cause__
                            if isinstance(cause, httpx.HTTPStatusError):
                                result["provider"] = (
                                    cause.response.json().get("error", {}).get("message")
                                )
                        finally:
                            debugger.get("/json/close/" + tab["id"])
                        print(json.dumps({"run": i + 1, "model": model, **result}), flush=True)
        finally:
            browser.terminate()
            browser.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
