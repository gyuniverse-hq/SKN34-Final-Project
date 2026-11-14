"""Exploratory aligned look comparison; no masks here are validated makeup boundaries."""
from __future__ import annotations

import csv
import argparse
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'research/data/look6'
spec = importlib.util.spec_from_file_location('blush_analysis', ROOT / 'research/karina_look/analyze_blush.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
spec = importlib.util.spec_from_file_location('color_metrics', ROOT / 'research/lip_texture/metrics.py')
color_metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(color_metrics)


def rgb2lab(rgb):
    return cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2Lab)

REGIONS = {
    'lip': ([61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146],),
    'blush': ([50, 101, 116, 117, 118, 123, 187, 205, 207], [280, 330, 345, 346, 347, 352, 411, 425, 427]),
    'eyeshadow': ([33, 46, 52, 53, 63, 105, 107, 133, 159, 160], [263, 276, 282, 283, 293, 334, 336, 362, 386, 387]),
    'brow': ([46, 52, 53, 63, 65, 66, 70, 105, 107], [276, 282, 283, 293, 295, 296, 300, 334, 336]),
    'contour': ([127, 132, 136, 172, 58, 172, 150], [356, 361, 365, 397, 288, 379, 400]),
    'highlighter': ([168, 6, 197, 195, 5, 4], [50, 101, 117, 118, 123], [280, 330, 346, 347, 352]),
    'foundation': ([10, 67, 103, 109, 234, 172, 152, 397, 454, 338, 297],),
    'eyeliner': ([33, 133, 159, 160, 161], [263, 362, 386, 387, 388]),
    'mascara': ([33, 133, 159, 160, 161], [263, 362, 386, 387, 388]),
}


def mask_for(pts, groups, shape):
    mask = np.zeros(shape, np.uint8)
    for group in groups:
        cv2.fillConvexPoly(mask, cv2.convexHull(np.round(pts[group]).astype(np.int32)), 1)
    return mask.astype(bool)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', help='only measure this video ID')
    args = parser.parse_args()
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        for frames_path in sorted(DATA.glob('*/frames.json')):
            frames = json.loads(frames_path.read_text(encoding='utf-8'))
            if args.video and frames['videoId'] != args.video:
                continue
            final = frames['selected']['final']
            out = frames_path.parent / 'baseline'
            if not final or not (out / 'off.png').exists():
                continue
            before = analysis.read_rgb(out / 'off.png')
            with Image.open(DATA / 'manual' / final) as image:
                target = np.asarray(ImageOps.pad(image.convert('RGB'), (before.shape[1], before.shape[0]), color=(32, 32, 32)))
            target = cv2.flip(target, 1)
            a, b = analysis.points(detector, before), analysis.points(detector, target)
            warped, covered = analysis.warp_mesh(target.astype(np.float32) / 255, b, a, before.shape[:2])
            aligned = np.clip(warped * 255, 0, 255).astype(np.uint8)
            cv2.imwrite(str(out / 'final_aligned.png'), cv2.cvtColor(aligned, cv2.COLOR_RGB2BGR))
            try:
                _, calibration = analysis.calibrate_background(before, target)
                calibration['note'] = 'background correspondence is unreliable when backgrounds differ; relative values remain exploratory'
            except RuntimeError as error:
                calibration = {'failed': str(error)}
            reference = mask_for(a, ([175, 199, 200, 18, 421, 201],), before.shape[:2]) & covered
            if reference.sum() < 30:
                raise RuntimeError('reference skin region unavailable')
            base_lab, target_lab = rgb2lab(before), rgb2lab(aligned)
            target_delta = target_lab - base_lab
            target_relative = target_delta - np.median(target_delta[reference], axis=0)
            result, rows = {}, []
            face_width = float(np.linalg.norm(a[234] - a[454]))
            for zone, groups in REGIONS.items():
                path = out / f'{zone}.png'
                if not path.exists() or not frames['zones'][zone]['exploratory']:
                    continue
                region = mask_for(a, groups, before.shape[:2]) & covered
                if region.sum() < 30:
                    continue
                ar = analysis.read_rgb(path)
                ar_lab = rgb2lab(ar)
                ar_delta = ar_lab - base_lab
                ar_relative = ar_delta - np.median(ar_delta[reference], axis=0)
                distance = np.linalg.norm(target_relative, axis=2)
                ar_distance = np.linalg.norm(ar_relative, axis=2)
                comparisons = {}
                for threshold in (3, 6, 9):
                    x, y = region & (distance > threshold), region & (ar_distance > threshold)
                    union = (x | y).sum()
                    center = None
                    if x.any() and y.any():
                        center = float(np.linalg.norm(np.argwhere(x).mean(axis=0) - np.argwhere(y).mean(axis=0)) / face_width)
                    comparisons[str(threshold)] = {'iou': float((x & y).sum() / union) if union else None, 'centerDistanceFaceWidths': center,
                                                   'candidatePixels': int(x.sum()), 'arPixels': int(y.sum())}
                ys, xs = np.where(region & (distance > 6))
                center = [float((xs.mean() - a[1, 0]) / face_width), float((ys.mean() - a[1, 1]) / face_width)] if len(xs) else None
                spread = [float(xs.std() * 2 / face_width), float(ys.std() * 2 / face_width)] if len(xs) else None
                weights = []
                for index in sorted(set(i for group in groups for i in group)):
                    x = min(max(round(float(a[index, 0])), 0), before.shape[1] - 1)
                    y = min(max(round(float(a[index, 1])), 0), before.shape[0] - 1)
                    weights.append({'index': index, 'relativeChangeLab': float(distance[y, x])})
                result[zone] = {'thresholds': comparisons, 'candidateCenterFromNoseFaceWidths': center,
                                'candidateSpread2SigmaFaceWidths': spread, 'landmarkSamples': weights,
                                'meanRelativeChangeLab': target_relative[region].mean(axis=0).tolist(),
                                'warning': 'change candidates only, not verified makeup boundaries'}
                ry, rx = np.where(region)
                pad = 20
                x0, x1 = max(0, rx.min() - pad), min(before.shape[1], rx.max() + pad + 1)
                y0, y1 = max(0, ry.min() - pad), min(before.shape[0], ry.max() + pad + 1)
                overlay = ((before.astype(np.float32) + aligned.astype(np.float32)) * 0.5).astype(np.uint8)
                sheet = np.hstack([im[y0:y1, x0:x1] for im in (before, ar, aligned, overlay)])
                cv2.imwrite(str(out / f'comparison_{zone}.png'), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
                base_edge = cv2.Laplacian(base_lab[:, :, 0].astype(np.float32), cv2.CV_32F)
                ar_edge = cv2.Laplacian(ar_lab[:, :, 0].astype(np.float32), cv2.CV_32F)
                target_edge = cv2.Laplacian(target_lab[:, :, 0].astype(np.float32), cv2.CV_32F)
                ar_samples, target_samples = ar_lab[region][::4], target_lab[region][::4]
                delta_e = np.mean([color_metrics.de2000(x, y) for x, y in zip(ar_samples, target_samples, strict=True)])
                rows.append({'zone': zone, 'deltaE2000_uncalibrated_sampled': float(delta_e),
                             'relative_change_lab_error': float(np.linalg.norm(ar_relative[region] - target_relative[region], axis=1).mean()),
                             'texture_edge_change_error': float(abs(np.std(ar_edge[region]) - np.std(base_edge[region]) - np.std(target_edge[region]) + np.std(base_edge[region]))),
                             'iou_threshold6': comparisons['6']['iou'], 'center_distance_face_widths': comparisons['6']['centerDistanceFaceWidths']})
            (frames_path.parent / 'zones_measured.json').write_text(json.dumps({'calibration': calibration, 'zones': result,
                'reference': 'lower chin; can contain foundation and is not an unchanged reference',
                'warning': 'exploratory only; lighting, segmentation, hair and image alignment may dominate changes'}, indent=2), encoding='utf-8')
            if rows:
                with (frames_path.parent / 'metrics_baseline.csv').open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
            print(frames['videoId'], 'exploratory zones', len(rows), 'background', calibration, flush=True)


if __name__ == '__main__':
    main()
