"""AR environment checks on real faces of three skin tone groups (Roboflow skin-tone-9drvk: dark / fair / light).

The skin and background come from the same MediaPipe Selfie Multiclass model the app runs (class 3 face skin,
0 background), so the measures match sampleScene on the phone. Each image is measured as-is (normal light) and with the
synthetic changes of lapa_env_eval.conditions (dark room, auto-exposed dark room, backlight, side light, warm, cool, blown).

    python research/env_eval/skin_tone_env_eval.py <skin_tone_dir> <selfie_multiclass.tflite> <out.csv> [per_class]
"""
import csv
import glob
import os
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lapa_env_eval import conditions, ita_of, measure  # noqa: E402


def main():
    root, model, out_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=model), output_category_mask=True))
    rows = []
    for cls in ['dark', 'fair', 'light']:
        files = sorted(glob.glob(os.path.join(root, '*', cls, '*')))[:per]
        for f in files:
            bgr = cv2.imread(f)
            if bgr is None:
                continue
            s = 720 / min(bgr.shape[:2])
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            cat = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).category_mask.numpy_view()
            cat = cv2.resize(cat.astype(np.uint8), (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_NEAREST)
            label = np.full(cat.shape, 2, np.uint8)
            label[cat == 0] = 0
            label[cat == 3] = 1
            if (label == 1).mean() < 0.05:
                continue
            ita = ita_of(rgb, label)
            for cond, img in conditions(rgb, label).items():
                rows.append(dict(img=os.path.basename(f)[:40], tone=cls, ita=ita, cond=cond, **measure(img, label)))
        print(cls, len(rows), flush=True)
    with open(out_csv, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print('rows', len(rows))


if __name__ == '__main__':
    main()
