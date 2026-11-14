"""Same-frame exploratory lip/blush search. Never registers or validates app profiles."""
from __future__ import annotations

import base64
import csv
import importlib.util
import io
import json
import time
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'research/data/look6'
VIDEO = 'ZAozXs-ZZik'
OUT = DATA / VIDEO / 'candidate_search'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    helper = load('offline_renderer', ROOT / 'research/lip_texture/render.py')
    measure = load('look_measure', ROOT / 'research/look6/measure.py')
    frames = json.loads((DATA / VIDEO / 'frames.json').read_text(encoding='utf8'))
    actual = json.loads((DATA / VIDEO / 'app_makeup.json').read_text(encoding='utf8'))['makeup']
    out = OUT
    out.mkdir(parents=True, exist_ok=True)
    with Image.open(DATA / 'manual' / frames['selected']['bare']) as source:
        buff = io.BytesIO()
        ImageOps.pad(source.convert('RGB'), (996, 560), color=(32, 32, 32)).save(buff, format='PNG')
        face = buff.getvalue()
    html = (DATA / 'page.html').read_text(encoding='utf8')
    html = html.replace('  function processFrame(now) {', '  function processFrame(now) {\n    if (window.__researchPaused) return;', 1)
    marker = '  // Prefer requestVideoFrameCallback (fires once per camera frame, AR_SPEC 6-1); else poll with rAF.'
    hook = '''  window.__researchDraw = (state) => {
      const old = makeup; makeup = state;
      try { renderer.render(video.videoWidth, video.videoHeight, false, false); }
      finally { makeup = old; }
    };
'''
    if html.count(marker) != 1:
        raise RuntimeError('renderer test hook missing')
    html = html.replace(marker, hook + marker, 1)
    zones = list(actual)
    cases = []
    for zone in ('lip', 'blush'):
        setting = actual[zone]
        cases.append((zone, 'baseline', setting))
        for multiplier in (0.5, 0.75, 1.25, 1.5):
            cases.append((zone, f'coverage_{multiplier}', {**setting, 'applicationProfile': {'coverageMultiplier': multiplier}}))
        if zone == 'lip':
            for detail in (0.3, 0.8):
                cases.append((zone, f'detail_{detail}', {**setting, 'applicationProfile': {'material': {'detail': detail}}}))
        else:
            for placement in ('apple', 'under_eye', 'side'):
                cases.append((zone, placement, {**setting, 'geometry': {'blushPlacement': placement}}))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True, args=['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        try:
            ctx = browser.new_context(viewport={'width': 996, 'height': 560}, ignore_https_errors=True)
            page = ctx.new_page()
            page.route('**/*', lambda route: route.abort())
            helper.routes(page, face, html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto('https://localhost/')
            helper.wait_status(page, 'tracking')
            time.sleep(10)
            page.evaluate("() => { window.__researchPaused = true; const t = performance.now(); Object.defineProperty(performance, 'now', { configurable: true, value: () => t }); }")
            blank = {zone: None for zone in zones}
            page.evaluate('s => window.__researchDraw(s)', blank)
            helper.shot(page, out / 'off.png')
            for zone, name, setting in cases:
                state = {**blank, zone: setting}
                page.evaluate('s => window.__researchDraw(s)', state)
                helper.shot(page, out / f'{zone}_{name}.png')
                print(zone, name, flush=True)
            ctx.close()
        finally:
            browser.close()
    before = measure.analysis.read_rgb(out / 'off.png')
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    scores = []
    targets = [('fit', frames['selected']['final']), ('angle_low_resolution', 'ZAozXs-ZZik_4_left.png'),
               ('angle_open_low_resolution', 'ZAozXs-ZZik_3_left.png'), ('open_small', 'ZAozXs-ZZik_2_open.png'),
               ('open_small_low_resolution', 'ZAozXs-ZZik_5_open.png'), ('angle_shallow_low_resolution', 'ZAozXs-ZZik_6_left.png')]
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        src = measure.analysis.points(detector, before)
        base_lab = measure.rgb2lab(before)
        for view, file in targets:
            with Image.open(DATA / 'manual' / file) as image:
                target = np.asarray(ImageOps.pad(image.convert('RGB'), (before.shape[1], before.shape[0]), color=(32, 32, 32)))
            target = cv2.flip(target, 1)
            target_pts = measure.analysis.points(detector, target)
            warped, covered = measure.analysis.warp_mesh(target.astype(np.float32) / 255, target_pts, src, before.shape[:2])
            target_rgb = np.uint8(np.clip(warped * 255, 0, 255))
            if view == 'fit':
                cv2.imwrite(str(out / 'final_aligned.png'), cv2.cvtColor(target_rgb, cv2.COLOR_RGB2BGR))
            target_lab = measure.rgb2lab(target_rgb)
            ref = measure.mask_for(src, ([175, 199, 200, 18, 421, 201],), before.shape[:2]) & covered
            if ref.sum() < 30:
                continue
            target_delta = target_lab - base_lab
            target_relative = target_delta - np.median(target_delta[ref], axis=0)
            for zone, name, setting in cases:
                region = measure.mask_for(src, measure.REGIONS[zone], before.shape[:2]) & covered
                if region.sum() < 30:
                    continue
                candidate = measure.analysis.read_rgb(out / f'{zone}_{name}.png')
                lab = measure.rgb2lab(candidate)
                delta = lab - base_lab
                relative = delta - np.median(delta[ref], axis=0)
                mismatch = float(np.linalg.norm(relative[region] - target_relative[region], axis=1).mean())
                samples = np.mean([measure.color_metrics.de2000(a, b) for a, b in zip(lab[region][::6], target_lab[region][::6], strict=True)])
                scores.append({'view': view, 'file': file, 'zone': zone, 'candidate': name,
                               'relative_lab_error': mismatch, 'deltaE_uncalibrated': float(samples),
                               'changed_pixels': int(np.any(candidate != before, axis=2).sum())})
    with (out / 'candidate_metrics.csv').open('w', newline='', encoding='utf8') as stream:
        writer = csv.DictWriter(stream, fieldnames=scores[0].keys())
        writer.writeheader(); writer.writerows(scores)
    (out / 'limitations.json').write_text(json.dumps({'status': 'exploratory_not_accepted', 'same_tracked_frame': True,
        'warnings': ['no turned bare image', 'angle images below 300px face width', 'background calibration failed',
                     'same video and nearby frames', 'open mouth target compared with closed bare geometry',
                     'chin reference may contain foundation', 'no opposite angle', 'no physical texture estimate']}, indent=2), encoding='utf8')
    for zone, candidate in (('lip', 'coverage_0.5'), ('blush', 'under_eye')):
        panels = [Image.open(out / name).convert('RGB').resize((498, 280)) for name in
                  ('off.png', f'{zone}_baseline.png', f'{zone}_{candidate}.png', 'final_aligned.png')]
        sheet = Image.new('RGB', (498 * len(panels), 280))
        for index, panel in enumerate(panels):
            sheet.paste(panel, (index * 498, 0))
        sheet.save(out / f'{zone}_comparison.png')
    print('Wrote exploratory candidate comparisons; no profiles accepted.')


if __name__ == '__main__':
    main()
