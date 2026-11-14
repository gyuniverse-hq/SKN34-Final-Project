"""Capture frames of one demo-look video from YouTube's playing video element; never download the file."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "look6"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# The six demo looks in lib/demoLookAr.ts. Only these videos may be captured.
VIDEOS = {"ZAozXs-ZZik", "4QR0tre9yBI", "kWI7_DkDjZ0", "n5otfjJSSQc", "e1gSkUdG6Bo", "fDqBPI1SaWY"}


def stop_if_blocked(page) -> None:
    body = page.locator("body").inner_text(timeout=10000).lower()
    if "consent.youtube.com" in page.url or any(text in body for text in (
        "sign in to confirm you’re not a bot", "sign in to confirm you're not a bot",
        "본인 확인", "로그인하여 본인 확인", "confirm your age",
    )):
        raise RuntimeError("YouTube login, bot verification, or consent screen; stopped")


def select_best_quality(page) -> int:
    page.locator(".html5-video-player").hover()
    page.locator(".ytp-settings-button").click()
    page.locator(".ytp-settings-menu .ytp-menuitem:visible").last.click()
    options = page.locator(".ytp-settings-menu .ytp-menuitem:visible")
    candidates = []
    for text in options.all_inner_texts():
        match = re.search(r"(\d+)p", text)
        if match and "premium" not in text.lower() and "프리미엄" not in text:
            candidates.append(int(match.group(1)))
    if not candidates:
        raise RuntimeError("No selectable quality found; stopped")
    quality = max(candidates)
    options.filter(has_text=re.compile(rf"^\s*{quality}p\b", re.IGNORECASE)).first.click()
    page.wait_for_timeout(3000)
    return quality


SETTLED = ("t => { const v=document.querySelector('video'); return v && !v.seeking "
           "&& v.readyState >= 2 && Math.abs(v.currentTime-t)<0.1; }")


def seek_paused(page, sec: float) -> None:
    # A paused <video> may never refill after a quality switch; the player's own seek fetches the range.
    for attempt in range(3):
        page.evaluate("t => { const p=document.querySelector('#movie_player'); p.pauseVideo(); p.seekTo(t, true); }", sec)
        try:
            page.wait_for_function(SETTLED, arg=sec, timeout=10000, polling=250)
            return
        except Exception:
            if attempt == 2:
                state = page.evaluate("() => { const v=document.querySelector('video'); "
                                      "return {t: v.currentTime, rs: v.readyState, seeking: v.seeking}; }")
                raise RuntimeError(f"Seek to {sec}s did not settle: {state}") from None
            # Let the player buffer briefly, then retry the exact seek.
            page.evaluate("() => document.querySelector('#movie_player').playVideo()")
            page.wait_for_timeout(1500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, choices=sorted(VIDEOS))
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--step", type=float, default=0.25)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--png", action="store_true", help="lossless 2x capture for measurement")
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
    out = (DATA / args.video / args.folder).resolve()
    if not out.is_relative_to(DATA.resolve()):
        parser.error("output must stay inside the ignored research data directory")
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROME, headless=True, args=["--autoplay-policy=no-user-gesture-required"]
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2 if args.png else 1)
            page.goto(f"https://www.youtube.com/watch?v={args.video}&t={int(args.start)}s",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            stop_if_blocked(page)
            # Do not skip advertisements; wait for playback to finish naturally.
            page.wait_for_function("() => !document.querySelector('.ad-showing')", timeout=120000, polling=500)
            quality = select_best_quality(page)
            page.add_style_tag(content=(
                ".ytp-chrome-top,.ytp-chrome-bottom,.ytp-gradient-top,.ytp-gradient-bottom,"
                ".ytp-pause-overlay,.ytp-cards-teaser,.ytp-ce-element,.ytp-watermark {visibility:hidden !important}"
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
                    page.wait_for_function("() => !document.querySelector('.ad-showing')", timeout=120000, polling=500)
                    stop_if_blocked(page)
                seek_paused(page, sec)
                state = video.evaluate("v => ({time:v.currentTime,width:v.videoWidth,height:v.videoHeight})")
                name = f"{i:04d}.png" if args.png else f"{i:04d}.jpg"
                if args.png:
                    video.screenshot(path=str(out / name))
                else:
                    video.screenshot(path=str(out / name), type="jpeg", quality=90)
                records.append({"file": name, "requested": sec, **state})
            (out / "capture_manifest.json").write_text(json.dumps({
                "video": args.video, "duration": duration, "selected_quality_p": quality, "frames": records,
            }, indent=2), encoding="utf-8")
            print(f"Captured {len(records)} frames to {out}; selected quality {quality}p")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
