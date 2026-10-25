"""Landmark lip mask vs LaPa ground-truth lip mask (AR_SPEC 6-5-3, plan track E).

Baseline for "how well does the MediaPipe lip outline match the real lip": the same 20 outer and
20 inner landmark indices the AR page uses (faceTrackerHtml.ts LIPS_OUTER / LIPS_INNER), filled
as outer polygon minus inner polygon, compared with LaPa labels 7 (upper lip) + 9 (lower lip).

LaPa is non-commercial (academic) data: it stays under research/data/ (git-ignored) and is used
for internal evaluation only. Nothing here is sent to a server (AR_SPEC 1-4).

    python research/lip_reference/eval_lapa.py            # all test images
    python research/lip_reference/eval_lapa.py --limit 50
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parents[2]
LAPA = ROOT / "research/data/reference/lapa/LaPa/test"
MODEL = ROOT / "research/data/models/face_landmarker.task"
OUT = ROOT / "research/data/reference/lapa/eval"

LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
UPPER_LIP, INNER_MOUTH, LOWER_LIP, SKIN = 7, 8, 9, 1


def make_landmarker():
    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.5,
    )
    return vision.FaceLandmarker.create_from_options(opts)


def polygon_mask(pts, shape):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 1)
    return m


def landmark_lip_mask(lms, w, h):
    pts = np.array([[l.x * w, l.y * h] for l in lms])
    outer = polygon_mask(pts[LIPS_OUTER], (h, w))
    inner = polygon_mask(pts[LIPS_INNER], (h, w))
    return (outer & (1 - inner)).astype(bool), pts


def frontal_score(pts):
    """Nose tip between the eye corners: 1 = frontal. Cheap yaw proxy from 2D landmarks."""
    left, right, nose = pts[33], pts[263], pts[1]
    t = (nose[0] - left[0]) / max(right[0] - left[0], 1e-6)
    return 1.0 - min(abs(t - 0.5) * 4.0, 1.0)


def skin_lightness(img_bgr, label):
    skin = label == SKIN
    if skin.sum() < 200:
        return float("nan")
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    return float(lab[..., 0][skin].mean() * 100.0 / 255.0)


def evaluate(name, landmarker):
    img = cv2.imread(str(LAPA / "images" / f"{name}.jpg"))
    label = cv2.imread(str(LAPA / "labels" / f"{name}.png"), cv2.IMREAD_UNCHANGED)
    if img is None or label is None:
        return None
    if label.ndim == 3:
        label = label[..., 0]
    h, w = label.shape
    gt = (label == UPPER_LIP) | (label == LOWER_LIP)
    if gt.sum() < 400:
        return None
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    row = {"name": name, "w": w, "h": h, "gt_px": int(gt.sum()), "lightness": skin_lightness(img, label),
           "open": float((label == INNER_MOUTH).sum() / max(gt.sum(), 1))}
    if not res.face_landmarks:
        row.update(detected=0)
        return row
    pred, pts = landmark_lip_mask(res.face_landmarks[0], w, h)
    inter = (pred & gt).sum()
    union = (pred | gt).sum()
    row.update(
        detected=1,
        frontal=frontal_score(pts),
        pred_px=int(pred.sum()),
        iou=float(inter / max(union, 1)),
        spill=float((pred & ~gt).sum() / max(pred.sum(), 1)),   # painted outside the real lip
        miss=float((gt & ~pred).sum() / max(gt.sum(), 1)),      # real lip left uncovered
    )
    return row


def dump_subset(landmarker):
    """Landmarks (px) of the 200-image subset, for scripts that run in another Python env."""
    names = json.loads((OUT / "subset200.json").read_text())
    out = {}
    for n in names:
        img = cv2.imread(str(LAPA / "images" / f"{n}.jpg"))
        h, w = img.shape[:2]
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        if res.face_landmarks:
            out[n] = [[l.x * w, l.y * h] for l in res.face_landmarks[0]]
    (OUT / "subset200_landmarks.json").write_text(json.dumps(out))
    print(f"dumped {len(out)} / {len(names)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dump-subset", action="store_true")
    args = ap.parse_args()
    if not MODEL.exists():
        sys.exit(f"missing {MODEL}")
    OUT.mkdir(parents=True, exist_ok=True)
    if args.dump_subset:
        dump_subset(make_landmarker())
        return
    names = sorted(p.stem for p in (LAPA / "images").glob("*.jpg"))
    if args.limit:
        names = names[: args.limit]
    lm = make_landmarker()
    rows = []
    for i, n in enumerate(names):
        r = evaluate(n, lm)
        if r:
            rows.append(r)
        if (i + 1) % 200 == 0:
            print(f"{i + 1}/{len(names)}", flush=True)
    keys = ["name", "w", "h", "gt_px", "lightness", "open", "detected", "frontal", "pred_px", "iou", "spill", "miss"]
    with open(OUT / "baseline_landmarks.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(rows)
    ok = [r for r in rows if r.get("detected")]
    print(f"images {len(rows)}  detected {len(ok)} ({100 * len(ok) / max(len(rows), 1):.1f}%)")
    for k in ("iou", "spill", "miss"):
        v = np.array([r[k] for r in ok])
        print(f"{k}: mean {v.mean():.3f}  median {np.median(v):.3f}  p10 {np.percentile(v, 10):.3f}  p90 {np.percentile(v, 90):.3f}")


if __name__ == "__main__":
    main()
