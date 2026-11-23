"""Dump the AR page's smoothed landmarks (sx, sy) for a still face, to compare with prep.py's image-mode points.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/dump_landmarks.py hs_d_by
Writes research/data/lip_texture/faces/<face>.page.json ({"x": [...], "y": [...]} in pixels, page = mirrored).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from render import CHROME, DATA, FAKE_CAMERA, page_html, routes, wait_status
import render


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("face")
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--offline-strict", action="store_true")
    args = ap.parse_args()
    face = args.face
    render.DATA = args.data_dir
    marker = "window.__kb = { receive: handleMessage };"
    html = page_html()
    assert html.count(marker) == 1
    html = html.replace(marker, marker + " window.__lm = () => [Array.from(sx), Array.from(sy)]; window.__light = () => JSON.parse(JSON.stringify(light));")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--enable-unsafe-swiftshader"])
        ctx = browser.new_context(viewport={"width": 720, "height": 960}, device_scale_factor=1, ignore_https_errors=True)
        page = ctx.new_page()
        page.add_init_script(FAKE_CAMERA)
        routes(page, (args.data_dir / "faces" / f"{face}.png").read_bytes(), html, offline_strict=args.offline_strict)
        page.goto("https://localhost/")
        wait_status(page, "tracking")
        time.sleep(4)
        xs, ys = page.evaluate("window.__lm()")
        light = page.evaluate("window.__light()")
        out = args.data_dir / "faces" / f"{face}.page.json"
        out.write_text(json.dumps({"x": [v * 720 for v in xs], "y": [v * 960 for v in ys], "light": light}))
        print(out, {k: light[k] for k in ("lipRed", "skinRed", "lipMeanLum", "lipColor")})
        browser.close()


if __name__ == "__main__":
    main()
