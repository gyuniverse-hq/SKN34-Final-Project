"""Render a bundled video-look zone on a candidate frame with the real WebView page.

The result is exploratory. Lip and blush candidate limitations are documented
in README.md. No frame is sent to a network service.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "karina_look"
HELPER = ROOT / "research" / "lip_texture" / "render.py"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", choices=("lip", "blush", "brow", "contour", "eyeshadow", "eyeliner", "all"), default="lip")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("lip_texture_render", HELPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the existing offline AR render helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    html = (DATA / "page.html").read_text(encoding="utf-8")
    sources = {
        "lip": "lip_input/0004.png", "blush": "blush_candidates/0012.png",
        "brow": "brow_scan/0003.png", "contour": "contour_scan/0003.png",
        "eyeshadow": "contour_scan/0022.png", "eyeliner": "liner_scan/0002.png",
        "all": "whole_before/0005.png",
    }
    source = DATA / sources[args.zone]
    face = source.read_bytes()
    actual = json.loads((DATA / "app_makeup.json").read_text(encoding="utf-8"))["makeup"]
    setting = actual if args.zone == "all" else actual.get(args.zone)
    if not setting:
        raise RuntimeError(f"The app hook did not resolve the {args.zone} setting")
    out = DATA / f"{args.zone}_baseline"
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=helper.CHROME,
            headless=True,
            args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
        )
        try:
            ctx = browser.new_context(viewport={"width": 996, "height": 560}, ignore_https_errors=True)
            page = ctx.new_page()
            # Unmatched requests, including external services, never leave the browser.
            page.route("**/*", lambda route: route.abort())
            helper.routes(page, face, html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto("https://localhost/")
            helper.wait_status(page, "tracking")
            time.sleep(6)
            page.locator("#canvas").screenshot(path=str(out / "off.png"))
            makeup = {zone: None for zone in (
                "lip", "blush", "eyeshadow", "eyeliner", "mascara", "highlighter", "contour", "brow", "foundation"
            )}
            if args.zone == "all":
                makeup = setting
            else:
                makeup[args.zone] = setting
            message = {"type": "makeup", "stateSeq": 1, "makeup": makeup}
            page.evaluate(
                "m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                message,
            )
            time.sleep(6)
            page.locator("#canvas").screenshot(path=str(out / f"{args.zone}.png"))
            print(f"Captured {args.zone}-only exploratory render from the app's resolved makeup state.")
            ctx.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
