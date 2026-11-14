"""Render the AR look strength slider positions on one bare photo and write a ladder sheet next to the video's final face."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import time

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

from blend_modes import DATA, ROOT, landmarks
from render_photos import PHOTOS, VIEW, face_box, panel, write

STRENGTHS = (0.3, 0.6, 1, 1.35, 1.7)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', default='e1gSkUdG6Bo')
    parser.add_argument('--photo', default='front', choices=sorted(PHOTOS))
    args = parser.parse_args()
    out = DATA / args.video / 'strength'
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('offline_renderer', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    html = (DATA / 'page.html').read_text(encoding='utf-8').replace('const TUNING = {', 'const TUNING = window.__TUNING = {', 1)
    marker = '  // Prefer requestVideoFrameCallback'
    html = html.replace(marker, """  window.__photoDraw = () => {
    window.__photoPaused = true;
    renderer.render(video.videoWidth, video.videoHeight, false, false);
  };
""" + marker, 1)
    html = html.replace('  function processFrame(now) {', '  function processFrame(now) {\n    if (window.__photoPaused) return;', 1)
    states = {f'{s}': json.loads((DATA / args.video / f'strength_{s}_makeup.json').read_text(encoding='utf-8'))['makeup'] for s in STRENGTHS}
    with Image.open(DATA / 'manual' / PHOTOS[args.photo]) as source:
        buffer = io.BytesIO()
        ImageOps.pad(source.convert('RGB'), VIEW, color=(32, 32, 32)).save(buffer, format='PNG')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                     args=['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        try:
            ctx = browser.new_context(viewport={'width': VIEW[0], 'height': VIEW[1]}, ignore_https_errors=True)
            page = ctx.new_page()
            page.route('**/*', lambda route: route.abort())
            helper.routes(page, buffer.getvalue(), html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto('https://localhost/')
            helper.wait_status(page, 'tracking')
            time.sleep(6)
            page.evaluate("() => Object.assign(window.__TUNING, {lightEveryMs: 1e12, segmentEveryMs: 1e12, segmentEveryMsAuto: 1e12})")
            time.sleep(2)
            page.evaluate('() => window.__photoDraw()')
            helper.shot(page, out / f'{args.photo}_bare.png', n=1)
            for seq, (name, state) in enumerate(states.items(), 1):
                page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                              {'type': 'makeup', 'stateSeq': seq, 'makeup': state})
                for _ in range(5):
                    page.evaluate('() => window.__photoDraw()')
                    time.sleep(0.2)
                helper.shot(page, out / f'{args.photo}_s{name}.png', n=1)
                print('rendered strength', name, flush=True)
            ctx.close()
        finally:
            browser.close()
    read = lambda p: cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)  # noqa: E731
    final = read(DATA / 'manual' / json.loads((DATA / args.video / 'frames.json').read_text(encoding='utf-8'))['selected']['final'])
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as det:
        bare = read(out / f'{args.photo}_bare.png')
        box = face_box(landmarks(det, bare), bare.shape)
        panels = [panel(bare, box, 'bare', 520)]
        panels += [panel(read(out / f'{args.photo}_s{s}.png'), box, f'strength {s}', 520) for s in STRENGTHS]
        if args.photo == 'front':
            panels.append(panel(final, face_box(landmarks(det, final), final.shape), 'video final', 520))
    write(out / f'{args.photo}_ladder.jpg', np.hstack(panels))
    print('wrote', out / f'{args.photo}_ladder.jpg')


if __name__ == '__main__':
    main()
