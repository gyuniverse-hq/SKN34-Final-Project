"""Re-frame the 200-image LaPa subset like a phone selfie (720x960, face ~55% of the height).

The AR page measures the lip edge on a camera frame, so the evaluation has to feed it frames of
the size it sees on a device, not the 1000+ px LaPa crops. Writes, per image, the frame (jpg),
the ground-truth lip mask (png, 255 = upper+lower lip) and the normalized MediaPipe landmarks.

    python research/lip_reference/prep_lapa_phone.py

Output stays under research/data/ (git-ignored; LaPa is non-commercial, AR_SPEC 1-4 / 1-7).
"""
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from eval_lapa import LAPA, LOWER_LIP, OUT as EVAL, UPPER_LIP, make_landmarker

W, H = 720, 960
FACE_FRAC = 0.55
OUT = EVAL.parent / "phone"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    names = json.loads((EVAL / "subset200.json").read_text())
    lm = make_landmarker()
    meta = {}
    for n in names:
        img = cv2.imread(str(LAPA / "images" / f"{n}.jpg"))
        label = cv2.imread(str(LAPA / "labels" / f"{n}.png"), cv2.IMREAD_UNCHANGED)
        label = label[..., 0] if label.ndim == 3 else label
        h, w = img.shape[:2]
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        if not res.face_landmarks:
            continue
        p = np.array([[l.x * w, l.y * h, l.z * w] for l in res.face_landmarks[0]])
        s = FACE_FRAC * H / max(abs(p[152, 1] - p[10, 1]), 1.0)
        c = p[:, :2].mean(0)
        M = np.array([[s, 0, W / 2 - s * c[0]], [0, s, H / 2 - s * c[1]]], np.float64)
        frame = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
        gt = ((label == UPPER_LIP) | (label == LOWER_LIP)).astype(np.uint8) * 255
        gt = cv2.warpAffine(gt, M, (W, H), flags=cv2.INTER_NEAREST, borderValue=0)
        cv2.imwrite(str(OUT / f"{n}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        cv2.imwrite(str(OUT / f"{n}_gt.png"), gt)
        xy = p[:, :2] @ M[:, :2].T + M[:, 2]
        meta[n] = {"x": (xy[:, 0] / W).round(5).tolist(), "y": (xy[:, 1] / H).round(5).tolist(),
                   "z": (p[:, 2] * s / W).round(5).tolist(), "scale": round(float(s), 3)}
    (OUT / "meta.json").write_text(json.dumps(meta))
    print(f"wrote {len(meta)} frames to {OUT}")


if __name__ == "__main__":
    main()
