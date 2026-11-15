"""Render one look (store state vs look mode) on several bare photos and write large comparison photos.

Exploratory, local only: the real AR page in headless Chrome with every network request blocked.
"""
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

VIEW = (1280, 720)
PHOTOS = {
    'front': 'e1gSkUdG6Bo_0001_bare.png', 'left': 'sullyoon_eval_left_bare.png', 'right': 'sullyoon_eval_right_bare.png',
    'open': 'sullyoon_eval_open_bare.png', 'other_strawberry': 'ZAozXs-ZZik_0_bare.png', 'other_yearend': '4QR0tre9yBI_0005_bare.png',
}


def render_all(video: str, out):
    spec = importlib.util.spec_from_file_location('offline_renderer', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    html = (DATA / 'page.html').read_text(encoding='utf-8').replace('const TUNING = {', 'const TUNING = window.__TUNING = {', 1)
    marker = '  // Prefer requestVideoFrameCallback'
    if marker not in html:
        raise RuntimeError('photo diagnostics marker missing')
    html = html.replace(marker, """  window.__photoSkin = () => Array.from(light.skinColor);
  window.__photoDraw = () => {
    window.__photoPaused = true;
    renderer.render(video.videoWidth, video.videoHeight, false, false);
  };
""" + marker, 1)
    html = html.replace('  function processFrame(now) {', '  function processFrame(now) {\n    if (window.__photoPaused) return;', 1)
    diagnostics = {}
    states = {name: json.loads((DATA / video / f'{name}_makeup.json').read_text(encoding='utf-8'))['makeup']
              for name in ('app', 'shown')}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                     args=['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        try:
            for label, file in PHOTOS.items():
                with Image.open(DATA / 'manual' / file) as source:
                    padded = ImageOps.pad(source.convert('RGB'), VIEW, color=(32, 32, 32))
                    buffer = io.BytesIO()
                    padded.save(buffer, format='PNG')
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
                # Hold one tracked frame across the bare/app/look captures. Rendering stays real; only tracking stops.
                page.evaluate('() => window.__photoDraw()')
                helper.shot(page, out / f'{label}_bare.png', n=1)
                for seq, name in enumerate(('app', 'shown'), 1):
                    page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                                  {'type': 'makeup', 'stateSeq': seq, 'makeup': states[name]})
                    for _ in range(5):
                        page.evaluate('() => window.__photoDraw()')
                        time.sleep(0.2)
                    helper.shot(page, out / f'{label}_{name}.png', n=1)
                print('rendered', label, flush=True)
                diagnostics[label] = {'skinColorLinear': page.evaluate('() => window.__photoSkin()')}
                ctx.close()
        finally:
            browser.close()
    (out / 'diagnostics.json').write_text(json.dumps(diagnostics, indent=2), encoding='utf-8')


def face_box(pts, shape, pad=0.35):
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    h, w = shape[:2]
    return max(0, int(x0 - px)), max(0, int(y0 - py)), min(w, int(x1 + px)), min(h, int(y1 + py))


def panel(img, box, label, height):
    x0, y0, x1, y1 = box
    crop = img[y0:y1, x0:x1]
    p = cv2.resize(crop, (round(crop.shape[1] * height / crop.shape[0]), height), interpolation=cv2.INTER_CUBIC)
    p = cv2.copyMakeBorder(p, 0, 40, 0, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(p, label, (8, height + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
    return p


def write(path, rgb):
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', default='e1gSkUdG6Bo')
    parser.add_argument('--skip-render', action='store_true')
    parser.add_argument('--previous-dir', action='append', default=None,
                        help='label=dir of earlier *_shown.png inside the video data folder (repeatable)')
    args = parser.parse_args()
    previous_dirs = [item.split('=', 1) for item in (args.previous_dir or ['previous look=photos_prev'])]
    out = DATA / args.video / 'photos'
    out.mkdir(parents=True, exist_ok=True)
    if not args.skip_render:
        render_all(args.video, out)
    read = lambda p: cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)  # noqa: E731
    final = read(DATA / 'manual' / json.loads((DATA / args.video / 'frames.json').read_text(encoding='utf-8'))['selected']['final'])
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as det:
        final_pts = landmarks(det, final)
        for label in PHOTOS:
            bare, app, shown = (read(out / f'{label}_{s}.png') for s in ('bare', 'app', 'shown'))
            previous = [(name, read(DATA / args.video / folder / f'{label}_shown.png')) for name, folder in previous_dirs]
            pts = landmarks(det, bare)
            box = face_box(pts, bare.shape)
            panels = [panel(bare, box, 'bare', 640), panel(app, box, 'product AR', 640)]
            panels += [panel(img, box, name, 640) for name, img in previous]
            panels.append(panel(shown, box, 'new look', 640))
            if label == 'front':
                panels.append(panel(final, face_box(final_pts, final.shape), 'video final', 640))
            write(out / f'{label}_compare.jpg', np.hstack(panels))
            if label == 'front':
                # Zoomed zones from the same pixels: current AR / look mode AR / video final, each cropped around its own landmarks.
                zones = {'eyes': [33, 133, 263, 362, 105, 334, 145, 374], 'cheeks': [234, 454, 117, 346, 205, 425, 4, 168],
                         'lips': [61, 291, 0, 17, 13, 14]}
                for zone, idx in zones.items():
                    tiles = []
                    rows = [('product AR', app, pts)] + [(name, img, pts) for name, img in previous]
                    rows += [('new look', shown, pts), ('video final', final, final_pts)]
                    for name, img, p in rows:
                        tiles.append(panel(img, face_box(p[idx], img.shape, pad=0.25), name, 360))
                    width = max(t.shape[1] for t in tiles)
                    tiles = [cv2.copyMakeBorder(t, 0, 0, 0, width - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
                    write(out / f'zoom_{zone}.jpg', np.vstack(tiles) if zone == 'eyes' else np.hstack(tiles))
    contact = []
    for label in PHOTOS:
        img = read(out / f'{label}_compare.jpg')
        contact.append(cv2.resize(img, (1600, round(img.shape[0] * 1600 / img.shape[1])), interpolation=cv2.INTER_AREA))
    write(out / 'all_views.jpg', np.vstack(contact))
    print(f'wrote photos to {out}')


if __name__ == '__main__':
    main()
