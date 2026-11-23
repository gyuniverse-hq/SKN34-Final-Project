"""Offline grain (lapa_env_eval.grain_at) of the first frame of each synthetic clip, to compare with the grain the page
reports in its HUD for the same clip (the page / offline ratio is the 0.45 factor in TUNING.env.dark).

    python research/env_eval/headless/offline_grain.py <selfie_multiclass.tflite> <out_json> <clip.y4m>...
"""
import json
import os
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from lapa_env_eval import grain_at  # noqa: E402


def first_frame(path):
    with open(path, 'rb') as fh:
        head = fh.readline().decode()
        w = int(head.split(' W')[1].split()[0]); h = int(head.split(' H')[1].split()[0])
        fh.readline()   # FRAME
        yuv = np.frombuffer(fh.read(w * h * 3 // 2), np.uint8).reshape(h * 3 // 2, w)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)


def main():
    model, out = sys.argv[1], sys.argv[2]
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=model), output_category_mask=True))
    res = {}
    for p in sys.argv[3:]:
        rgb = first_frame(p)
        cat = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).category_mask.numpy_view()
        cat = cv2.resize(cat.astype(np.uint8), (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_NEAREST)
        res[os.path.basename(p)[:-4]] = round(grain_at(rgb, cat == 3), 4)
    json.dump(res, open(out, 'w'), indent=1)
    print(res)


if __name__ == '__main__':
    main()
