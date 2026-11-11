"""Compare old and new AR pages on the same fake camera with no profiles.

Research-only HTML modifications freeze the first tracked face and scene sampling.
Network requests other than the local in-memory assets are blocked. The render
still runs in Chrome, so this is not a substitute for Expo Go device checks.
"""

from __future__ import annotations

import importlib.util
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/karina_look"
OUT = DATA / "unprofiled_regression"


def main() -> None:
    spec = importlib.util.spec_from_file_location("offline_render", ROOT / "research/lip_texture/render.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing existing offline render helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    OUT.mkdir(parents=True, exist_ok=True)
    face = (DATA / "whole_before/0005.png").read_bytes()
    makeup = json.loads((DATA / "app_makeup.json").read_text(encoding="utf-8"))["makeup"]
    if any(zone and zone.get("applicationProfile") for zone in makeup.values()):
        raise RuntimeError("Expected the real unprofiled app state")
    # Face-shape inference is time-dependent and may finish at different times
    # in two browser runs. Pin an existing highlighter layout identically.
    if makeup.get("highlighter"):
        geometry = dict(makeup["highlighter"].get("geometry") or {})
        geometry["hlFace"] = "oval"
        makeup["highlighter"]["geometry"] = geometry
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                     args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        try:
            for label, filename in (("before", "page_before_profiles.html"), ("after", "page_after_profiles.html")):
                html = (DATA / filename).read_text(encoding="utf-8")
                detect = "landmarker.detectForVideo(video, now)"
                if html.count(detect) != 1 or html.count("const TUNING = {") != 1:
                    raise RuntimeError("Cannot freeze the research tracker")
                html = html.replace(detect, "(window.__fixedFace || ((r) => r.faceLandmarks && r.faceLandmarks.length ? (window.__fixedFace = r) : r)(landmarker.detectForVideo(video, now)))")
                html = html.replace("const TUNING = {", "const TUNING = window.__TUNING = {")
                ctx = browser.new_context(viewport={"width": 996, "height": 560}, ignore_https_errors=True)
                page = ctx.new_page()
                page.route("**/*", lambda route: route.abort())
                helper.routes(page, face, html)
                page.add_init_script(helper.FAKE_CAMERA)
                page.goto("https://localhost/")
                helper.wait_status(page, "tracking")
                time.sleep(8)
                page.evaluate("""() => Object.assign(window.__TUNING, {
                    lightEveryMs: 1e12, segmentEveryMs: 1e12, segmentEveryMsAuto: 1e12
                })""")
                page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                              {"type": "makeup", "stateSeq": 1, "makeup": makeup})
                time.sleep(10)
                frame = np.asarray(Image.open(io.BytesIO(page.locator("#canvas").screenshot())).convert("RGB"))
                Image.fromarray(frame).save(OUT / f"{label}.png")
                results.append(frame)
                print("captured", label, flush=True)
                ctx.close()
        finally:
            browser.close()
    diff = np.abs(results[0].astype(np.int16) - results[1].astype(np.int16))
    summary = {"exactly_equal": bool(np.array_equal(*results)), "different_pixels": int(np.any(diff, axis=2).sum()),
               "max_channel_difference": int(diff.max()), "mean_channel_difference": float(diff.mean())}
    (OUT / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    if not summary["exactly_equal"]:
        raise SystemExit("Pixel equality not established")


if __name__ == "__main__":
    main()
