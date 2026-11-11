"""Capture YouTube's playing video element only, never download the video file."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "karina_look"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
VIDEO_URL = "https://www.youtube.com/watch?v=n5otfjJSSQc"


def stop_if_blocked(page) -> None:
    body = page.locator("body").inner_text(timeout=10000).lower()
    if "consent.youtube.com" in page.url or any(text in body for text in (
        "sign in to confirm you’re not a bot", "sign in to confirm you're not a bot",
        "본인 확인", "로그인하여 본인 확인", "confirm your age",
    )):
        raise RuntimeError("YouTube login, bot verification, or consent screen; stopped")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--step", type=float, default=0.25)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]+", args.folder):
        parser.error("folder must contain only lowercase ASCII letters, digits, and underscores")
    if not all(math.isfinite(x) for x in (args.start, args.end, args.step)):
        parser.error("times must be finite")
    if args.start < 0 or args.end < args.start or args.step < 0.05:
        parser.error("invalid start, end, or step")
    count = math.floor((args.end - args.start) / args.step + 1e-8) + 1
    if count > 200:
        parser.error("capture at most 200 frames per run")
    out = (DATA / args.folder).resolve()
    if not out.is_relative_to(DATA.resolve()):
        parser.error("output must stay inside the ignored research data directory")
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required"]
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
            page.goto(f"{VIDEO_URL}&t={int(args.start)}s", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            stop_if_blocked(page)
            # Do not skip advertisements; wait for playback to finish naturally.
            page.wait_for_function("() => !document.querySelector('.ad-showing')", timeout=60000)
            page.locator(".html5-video-player").hover()
            page.locator(".ytp-settings-button").click()
            page.locator(".ytp-settings-menu .ytp-menuitem:visible").last.click()
            options = page.locator(".ytp-settings-menu .ytp-menuitem:visible")
            choices = options.all_inner_texts()
            candidates = []
            for i, text in enumerate(choices):
                match = re.search(r"(\d+)p", text)
                if match and "premium" not in text.lower() and "프리미엄" not in text:
                    candidates.append((int(match.group(1)), i))
            if not candidates:
                raise RuntimeError("No selectable quality found; stopped")
            quality, _ = max(candidates)
            # The main menu can briefly remain visible while the quality menu
            # animates. Select by label, not its transient list index.
            options.filter(has_text=re.compile(rf"^\s*{quality}p\b", re.IGNORECASE)).first.click()
            page.wait_for_timeout(3000)
            page.add_style_tag(content=(
                ".ytp-chrome-top,.ytp-chrome-bottom,.ytp-gradient-top,.ytp-gradient-bottom,"
                ".ytp-pause-overlay,.ytp-cards-teaser {visibility:hidden !important}"
            ))
            video = page.locator("video").first
            duration = video.evaluate("v => v.duration")
            if not duration or args.end > duration:
                raise RuntimeError(f"Requested range exceeds video duration {duration}")
            records = []
            for i in range(count):
                sec = round(args.start + i * args.step, 4)
                stop_if_blocked(page)
                if page.locator(".ad-showing").count():
                    page.wait_for_function("() => !document.querySelector('.ad-showing')", timeout=60000)
                    stop_if_blocked(page)
                video.evaluate("(v,t) => { v.pause(); v.currentTime=t; }", sec)
                page.wait_for_function(
                    "t => { const v=document.querySelector('video'); return v && !v.seeking "
                    "&& v.readyState >= 2 && Math.abs(v.currentTime-t)<0.1; }",
                    arg=sec, timeout=25000,
                )
                state = video.evaluate("v => ({time:v.currentTime,width:v.videoWidth,height:v.videoHeight})")
                actual_quality = page.evaluate("() => document.querySelector('#movie_player')?.getPlaybackQuality?.()")
                name = f"{i:04d}.png"
                video.screenshot(path=str(out / name))
                records.append({"file": name, "requested": sec, **state, "quality": actual_quality})
            (out / "capture_manifest.json").write_text(json.dumps({
                "duration": duration, "selected_quality_p": quality, "frames": records,
            }, indent=2), encoding="utf-8")
            print(f"Captured {len(records)} frames to {out}; selected quality {quality}p")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
