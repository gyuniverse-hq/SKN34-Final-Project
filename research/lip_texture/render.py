"""Offline renders of the app's AR page (the real shader) on still faces, for lip texture checks.

The page from build_html.mjs runs in headless Chrome. A still face (prep.py) is the camera
(a canvas stream), MediaPipe files come from research/data (no CDN), and TUNING is exposed so each
config is rendered on the same tracked frame: only the named TUNING values differ between images.

Run (after `node research/lip_texture/build_html.mjs` and prep.py):
  research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/render.py --tag before \
      --config base= --config nogloss='{"glossGain":0,"lipSheen":0,"lipGlint":0}'
Outputs research/data/lip_texture/renders/<tag>/<face>__<shade>__<config>.png and <face>__off.png.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_texture"
MP_WEB = ROOT / "research" / "data" / "mediapipe-web"
MODELS = ROOT / "research" / "data" / "models"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

FACES = ["hs_a_cc0", "hs_b_by", "hs_c_by", "hs_d_by", "urban_model"]
SHADES = {
    "glossy_red": {"hex": "#B3202E", "texture": "glossy"},
    "glossy_rose": {"hex": "#D9707A", "texture": "glossy"},
    "satin_red": {"hex": "#B3202E", "texture": "satin"},
    "satin_coral": {"hex": "#C8604F", "texture": "satin"},
    "matte_red": {"hex": "#B3202E", "texture": "matte"},
}
INTENSITY = 0.6

FAKE_CAMERA = """
window.__msgs = [];
window.ReactNativeWebView = { postMessage: (s) => window.__msgs.push(s) };
const __img = new Image();
__img.src = 'https://localhost/face.png';
navigator.mediaDevices.getUserMedia = async () => {
  await __img.decode();
  const c = document.createElement('canvas');
  c.width = __img.naturalWidth; c.height = __img.naturalHeight;
  const ctx = c.getContext('2d');
  const draw = () => { ctx.drawImage(__img, 0, 0); requestAnimationFrame(draw); };
  draw();
  return c.captureStream(30);
};
"""


def page_html() -> str:
    html = (DATA / "page.html").read_text(encoding="utf-8")
    marker = "const TUNING = {"
    assert html.count(marker) == 1, "TUNING declaration not found"
    return html.replace(marker, "const TUNING = window.__TUNING = {")


def routes(page: Page, face_png: bytes, html: str) -> None:
    def fulfill(body: bytes, ctype: str):
        return lambda route: route.fulfill(status=200, body=body, headers={"content-type": ctype, "access-control-allow-origin": "*"})

    page.route("https://localhost/", fulfill(html.encode("utf-8"), "text/html"))
    page.route("https://localhost/face.png", fulfill(face_png, "image/png"))

    def mp(route: Route) -> None:
        url = route.request.url
        name = url.rsplit("/", 1)[1]
        if name == "vision_bundle.mjs":
            route.fulfill(body=(MP_WEB / name).read_bytes(), headers={"content-type": "text/javascript", "access-control-allow-origin": "*"})
        elif name.endswith(".wasm"):
            route.fulfill(body=(MP_WEB / "wasm" / name).read_bytes(), headers={"content-type": "application/wasm", "access-control-allow-origin": "*"})
        elif name.endswith(".js"):
            route.fulfill(body=(MP_WEB / "wasm" / name).read_bytes(), headers={"content-type": "text/javascript", "access-control-allow-origin": "*"})
        else:
            route.abort()

    page.route("https://cdn.jsdelivr.net/**", mp)
    page.route("**/face_landmarker.task", fulfill((MODELS / "face_landmarker.task").read_bytes(), "application/octet-stream"))
    page.route("**/selfie_multiclass_256x256.tflite", fulfill((MODELS / "selfie_multiclass.tflite").read_bytes(), "application/octet-stream"))


def wait_status(page: Page, want: str, timeout_s: float = 90) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        msgs = page.evaluate("window.__msgs.splice(0)")
        for m in msgs:
            d = json.loads(m)
            if d.get("type") == "status":
                if d.get("status") == want:
                    return
                if d.get("status") in ("unavailable", "denied"):
                    raise RuntimeError(f"page status {d}")
        time.sleep(0.25)
    raise TimeoutError(f"no '{want}' status")


def send_makeup(page: Page, lip: dict | None) -> None:
    msg = {"type": "makeup", "makeup": {"lip": lip, "blush": None, "eyeshadow": None}}
    page.evaluate("(m) => window.__kb.receive(JSON.stringify(m))", msg)


def set_tuning(page: Page, defaults: dict, override: dict) -> None:
    page.evaluate("([d, o]) => { Object.assign(window.__TUNING, JSON.parse(JSON.stringify(d)), o); }", [defaults, override])


def shot(page: Page, path: Path, n: int = 3) -> None:
    # Pixel median of a few frames: the landmarks jitter by a fraction of a pixel on a still image (lip edge).
    frames = []
    for i in range(n):
        if i:
            time.sleep(0.25)
        frames.append(np.asarray(Image.open(io.BytesIO(page.locator("#canvas").screenshot())).convert("RGB")))
    Image.fromarray(np.median(np.stack(frames), axis=0).astype(np.uint8)).save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--config", action="append", default=[], help="name=JSON TUNING override (empty = defaults)")
    ap.add_argument("--faces", default=",".join(FACES))
    ap.add_argument("--shades", default=",".join(SHADES))
    ap.add_argument("--settle", type=float, default=5.0)
    args = ap.parse_args()
    configs = {}
    for c in args.config or ["base="]:
        name, _, js = c.partition("=")
        configs[name] = json.loads(js) if js.strip() else {}
    out = DATA / "renders" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    html = page_html()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                     args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"])
        for face in args.faces.split(","):
            ctx = browser.new_context(viewport={"width": 720, "height": 960}, device_scale_factor=1, ignore_https_errors=True)
            page = ctx.new_page()
            page.on("pageerror", lambda e: print("pageerror", e))
            page.add_init_script(FAKE_CAMERA)
            routes(page, (DATA / "faces" / f"{face}.png").read_bytes(), html)
            page.goto("https://localhost/")
            wait_status(page, "tracking")
            defaults = page.evaluate("JSON.parse(JSON.stringify(window.__TUNING))")
            time.sleep(args.settle)
            # Freeze the light / lip-mean estimate (0.5 s) and segmentation once settled, so configs differ only by their own values.
            defaults.update(lightEveryMs=1e12, segmentEveryMs=1e12, segmentEveryMsAuto=1e12)
            set_tuning(page, defaults, {})
            time.sleep(3.0)
            send_makeup(page, None)
            time.sleep(1.0)
            shot(page, out / f"{face}__off.png")
            for shade in args.shades.split(","):
                send_makeup(page, dict(SHADES[shade], intensity=INTENSITY))
                time.sleep(1.5)
                for name, override in configs.items():
                    set_tuning(page, defaults, override)
                    time.sleep(0.4)
                    shot(page, out / f"{face}__{shade}__{name}.png")
                set_tuning(page, defaults, {})
            print(face, "done")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
