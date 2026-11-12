"""Render available look states locally over user-provided bare frames; no external requests."""
from __future__ import annotations

import importlib.util
import argparse
import io
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'research/data/look6'
ZONES = ('lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', help='only render this video ID')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('offline_renderer', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    html = (DATA / 'page.html').read_text(encoding='utf-8').replace('const TUNING = {', 'const TUNING = window.__TUNING = {', 1)
    for frames_path in sorted(DATA.glob('*/frames.json')):
        frames = json.loads(frames_path.read_text(encoding='utf-8'))
        if args.video and frames['videoId'] != args.video:
            continue
        bare = frames['selected']['bare']
        if not bare:
            continue
        directory = frames_path.parent
        # Match the render viewport without cropping the user's differently sized capture.
        with Image.open(DATA / 'manual' / bare) as source:
            padded = ImageOps.pad(source.convert('RGB'), (996, 560), color=(32, 32, 32))
            buffer = io.BytesIO()
            padded.save(buffer, format='PNG')
            face = buffer.getvalue()
        makeup = json.loads((directory / 'app_makeup.json').read_text(encoding='utf-8'))['makeup']
        out = directory / 'baseline'
        out.mkdir(exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                         args=['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
            try:
                ctx = browser.new_context(viewport={'width': 996, 'height': 560}, ignore_https_errors=True)
                page = ctx.new_page()
                page.route('**/*', lambda route: route.abort())
                helper.routes(page, face, html)
                page.add_init_script(helper.FAKE_CAMERA)
                page.goto('https://localhost/')
                helper.wait_status(page, 'tracking')
                time.sleep(6)
                page.evaluate("() => Object.assign(window.__TUNING, {lightEveryMs: 1e12, segmentEveryMs: 1e12, segmentEveryMsAuto: 1e12})")
                time.sleep(2)
                helper.shot(page, out / 'off.png')
                for seq, name in enumerate(('all', *ZONES), 1):
                    if name != 'all' and not makeup.get(name):
                        continue
                    state = makeup if name == 'all' else {zone: makeup.get(zone) if zone == name else None for zone in ZONES}
                    page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                                  {'type': 'makeup', 'stateSeq': seq, 'makeup': state})
                    time.sleep(1.5)
                    helper.shot(page, out / f'{name}.png')
                    print(frames['videoId'], name, flush=True)
                ctx.close()
            finally:
                browser.close()


if __name__ == '__main__':
    main()
