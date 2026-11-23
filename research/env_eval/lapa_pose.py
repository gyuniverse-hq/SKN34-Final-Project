"""Head turn on LaPa faces with the app's Face Landmarker model: the renderer's landmark formula (envEvaluate) against the
model's own facial transformation matrix (reference). Also gives the frontal subset for the light measures.

    python research/env_eval/lapa_pose.py <lapa_test_dir> <face_landmarker.task> <names.csv> <out.csv>

names.csv: any CSV with an 'img' column (e.g. the lapa_env_eval output); each name is measured once.
"""
import csv
import math
import os
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions


def main():
    root, model, names_csv, out_csv = sys.argv[1:5]
    names = sorted({r['img'] for r in csv.DictReader(open(names_csv))})
    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model), output_facial_transformation_matrixes=True, num_faces=1))
    rows = []
    for n in names:
        bgr = cv2.imread(os.path.join(root, 'images', n + '.jpg'))
        if bgr is None:
            continue
        H, W = bgr.shape[:2]
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
        if not res.face_landmarks:
            rows.append(dict(img=n, found=0)); continue
        p = res.face_landmarks[0]
        x = lambda i: p[i].x; y = lambda i: p[i].y; z = lambda i: p[i].z
        # Renderer formulas (faceTrackerHtml envEvaluate): sx/sy/sz are the normalised landmarks.
        yaw_f = math.degrees(math.atan((z(234) - z(454)) / max(1e-4, abs(x(234) - x(454)))))
        pitch_f = math.degrees(math.atan((z(10) - z(152)) / max(1e-4, abs(y(10) - y(152)) * H / W)))
        M = np.array(res.facial_transformation_matrixes[0])[:3, :3]
        # Yaw about the vertical axis, pitch about the horizontal one (camera looking down -z).
        yaw_m = math.degrees(math.atan2(-M[2, 0], math.hypot(M[2, 1], M[2, 2])))
        pitch_m = math.degrees(math.atan2(M[2, 1], M[2, 2]))
        rows.append(dict(img=n, found=1, yaw_f=yaw_f, pitch_f=pitch_f, yaw_m=yaw_m, pitch_m=pitch_m))
    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['img', 'found', 'yaw_f', 'pitch_f', 'yaw_m', 'pitch_m'])
        w.writeheader(); w.writerows(rows)
    print('rows', len(rows), 'found', sum(r['found'] for r in rows))


if __name__ == '__main__':
    main()
