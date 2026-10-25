"""BiSeNet face-parsing lips vs LaPa ground truth on the 200-image subset (plan track E / A5).

Runs where onnxruntime is installed (not the project's Python). Needs, from eval_lapa.py:
    python eval_lapa.py --dump-subset      # subset200_landmarks.json (mouth/face boxes)
Weights: research/data/models/bisenet_resnet18.onnx (yakhyo/face-parsing, MIT code; the
CelebAMask-HQ training data is non-commercial, so this is an evaluation, not a shipping decision).

Compares, on identical images and the same metrics as the landmark baseline:
  face   - 512px crop of the whole face (what a server-less app could never afford every frame)
  mouth  - 512px crop around the mouth (ONNX input is fixed at 512; detail ceiling for a mouth-only pass)
"""
import csv
import json
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[2]
LAPA = ROOT / "research/data/reference/lapa/LaPa/test"
EVAL = ROOT / "research/data/reference/lapa/eval"
MODEL = ROOT / "research/data/models/bisenet_resnet18.onnx"
CELEB_U_LIP, CELEB_L_LIP = 12, 13
LAPA_U_LIP, LAPA_L_LIP = 7, 9
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]


def square_crop(img, cx, cy, side):
    """Crop a square (padding with edge pixels) and return it with its top-left origin."""
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    s = int(round(side))
    pad = s
    padded = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    return padded[y0 + pad:y0 + pad + s, x0 + pad:x0 + pad + s], x0, y0


def lips_from_crop(sess, crop, size):
    rgb = cv2.cvtColor(cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = ((rgb.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)[None]
    t0 = time.perf_counter()
    out = sess.run(None, {"input": x})[0][0]
    ms = (time.perf_counter() - t0) * 1000
    cls = out.argmax(0)
    lips = ((cls == CELEB_U_LIP) | (cls == CELEB_L_LIP)).astype(np.uint8)
    return lips, ms


def paste_back(lips, x0, y0, side, shape):
    h, w = shape
    s = int(round(side))
    up = cv2.resize(lips, (s, s), interpolation=cv2.INTER_NEAREST)
    full = np.zeros((h, w), np.uint8)
    xa, ya = max(x0, 0), max(y0, 0)
    xb, yb = min(x0 + s, w), min(y0 + s, h)
    if xb > xa and yb > ya:
        full[ya:yb, xa:xb] = up[ya - y0:yb - y0, xa - x0:xb - x0]
    return full.astype(bool)


def main():
    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    lms = json.loads((EVAL / "subset200_landmarks.json").read_text())
    rows = []
    for name, pts in lms.items():
        img = cv2.imread(str(LAPA / "images" / f"{name}.jpg"))
        label = cv2.imread(str(LAPA / "labels" / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        label = label[..., 0] if label.ndim == 3 else label
        h, w = label.shape
        gt = (label == LAPA_U_LIP) | (label == LAPA_L_LIP)
        p = np.array(pts)
        face_c, face_side = p.mean(0), max(np.ptp(p[:, 0]), np.ptp(p[:, 1])) * 1.4
        mouth = p[LIPS_OUTER]
        mouth_c = (mouth.min(0) + mouth.max(0)) / 2
        mouth_side = max(np.ptp(mouth[:, 0]), np.ptp(mouth[:, 1])) * 1.8
        row = {"name": name}
        for tag, (c, side, size) in {"face": (face_c, face_side, 512), "mouth": (mouth_c, mouth_side, 512)}.items():
            crop, x0, y0 = square_crop(img, c[0], c[1], side)
            lips, ms = lips_from_crop(sess, crop, size)
            pred = paste_back(lips, x0, y0, side, (h, w))
            row[f"{tag}_iou"] = (pred & gt).sum() / max((pred | gt).sum(), 1)
            row[f"{tag}_spill"] = (pred & ~gt).sum() / max(pred.sum(), 1)
            row[f"{tag}_miss"] = (gt & ~pred).sum() / max(gt.sum(), 1)
            row[f"{tag}_ms"] = ms
        rows.append(row)
    with open(EVAL / "bisenet_subset200.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    for tag in ("face", "mouth"):
        for k in ("iou", "spill", "miss", "ms"):
            v = np.array([r[f"{tag}_{k}"] for r in rows])
            print(f"{tag:5s} {k:5s} mean {v.mean():.3f}  median {np.median(v):.3f}  p10 {np.percentile(v, 10):.3f}  p90 {np.percentile(v, 90):.3f}")


if __name__ == "__main__":
    main()
