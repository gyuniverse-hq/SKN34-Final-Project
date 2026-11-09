"""Writes face.y4m: a still face as a 720x960 portrait camera frame for Edge's fake camera (drive.mjs).

    python research/ar_repro/make_y4m.py <face.jpg> <out_dir>
The face photo is yours (e.g. a LaPa test image kept under the git-ignored research/data/); nothing is committed.
"""
import sys

import cv2
import numpy as np

img = cv2.imread(sys.argv[1])
h, w = img.shape[:2]
W, H = 720, 960
s = min(W / w, H / h)
r = cv2.resize(img, (int(w * s), int(h * s)))
frame = np.zeros((H, W, 3), np.uint8)
y0, x0 = (H - r.shape[0]) // 2, (W - r.shape[1]) // 2
frame[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
with open(sys.argv[2] + "/face.y4m", "wb") as f:
    f.write(b"YUV4MPEG2 W%d H%d F30:1 Ip A1:1 C420jpeg\n" % (W, H))
    for _ in range(30):
        f.write(b"FRAME\n")
        f.write(yuv.tobytes())
print("face.y4m", W, H)
