"""Tone values of the Roboflow dark-face-detector images (real night scenes), to see whether they are usable as real
low-light examples: are they the original dark frames, or already brightened / greyscale?

    python research/env_eval/dark_face_tone.py <dark_face_dir> <out.csv>

Per image: lapa_env_eval.tone_of on a 128 px wide copy, plus colourfulness (mean |R-G| + |G-B| on 0..255; ~0 = greyscale).
"""
import csv
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lapa_env_eval import tone_of  # noqa: E402


def main():
    root, out = sys.argv[1], sys.argv[2]
    rows = []
    for f in sorted(glob.glob(os.path.join(root, '*', '*.jpg'))):
        bgr = cv2.imread(f)
        if bgr is None:
            continue
        h, w = bgr.shape[:2]
        small = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (128, max(1, round(128 * h / w))), interpolation=cv2.INTER_AREA)
        s = small.astype(np.int16)
        colourful = float((np.abs(s[..., 0] - s[..., 1]) + np.abs(s[..., 1] - s[..., 2])).mean())
        rows.append(dict(img=os.path.basename(f)[:60], split=os.path.basename(os.path.dirname(f)), colourful=colourful, **tone_of(small)))
    with open(out, 'w', newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader(); wr.writerows(rows)
    print('rows', len(rows))


if __name__ == '__main__':
    main()
