"""Scan a look video: every STEP seconds find the face, record eye size / openness / yaw proxy."""
import sys, json, math
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision

vid, out, step = sys.argv[1], sys.argv[2], float(sys.argv[3])
model = sys.argv[4]
opts = vision.FaceLandmarkerOptions(
    base_options=mpp.BaseOptions(model_asset_path=model),
    running_mode=vision.RunningMode.IMAGE, num_faces=1)
lm = vision.FaceLandmarker.create_from_options(opts)
cap = cv2.VideoCapture(vid)
fps = cap.get(cv2.CAP_PROP_FPS) or 30
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
every = max(1, int(round(step * fps)))
rows = []
i = 0
while i < n:
    ok = cap.grab()
    if not ok:
        break
    if i % every == 0:
        ok, fr = cap.retrieve()
        if ok:
            rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
            r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if r.face_landmarks:
                p = np.array([[q.x * fr.shape[1], q.y * fr.shape[0]] for q in r.face_landmarks[0]])
                # eye corners: right eye 33/133, left eye 362/263; lids 159/145, 386/374
                wR = np.linalg.norm(p[33] - p[133]); wL = np.linalg.norm(p[362] - p[263])
                gR = np.linalg.norm(p[159] - p[145]) / max(wR, 1); gL = np.linalg.norm(p[386] - p[374]) / max(wL, 1)
                mid = (p[33] + p[263]) / 2
                yaw = (p[1][0] - mid[0]) / max(np.linalg.norm(p[33] - p[263]), 1)
                rows.append(dict(f=i, t=round(i / fps, 2), wR=round(float(wR), 1), wL=round(float(wL), 1),
                                 gR=round(float(gR), 3), gL=round(float(gL), 3), yaw=round(float(yaw), 3),
                                 face=round(float(np.linalg.norm(p[234] - p[454]) / W), 3)))
    i += 1
json.dump(dict(video=vid, fps=fps, n=n, rows=rows), open(out, 'w'))
print(vid.split('/')[-1], 'frames', n, 'sampled faces', len(rows))
