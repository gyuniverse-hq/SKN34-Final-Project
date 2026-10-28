"""Lash-wing stroke vs hand labels and BiSeNet eye region (research only).

Does not import app/, components/, or faceTrackerHtml.ts. Live AR stays on MediaPipe points
and EYELINER_PRESET.lineWing. CelebAMask-HQ training data is non-commercial: BiSeNet is
evaluation only (AR_SPEC 1-7, 1-13).

Hand labels (optional): research/data/liner/gt/{name}.png  — white = liner
Photos: research/data/liner/images/{name}.jpg  or LaPa test images if that tree exists.

    python research/liner_reference/eval_liner.py --limit 50
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/lip_reference"))
from eval_lapa import MODEL, frontal_score, make_landmarker  # noqa: E402

from stroke import stroke_mask  # noqa: E402

LINER_IMG = ROOT / "research/data/liner/images"
LINER_GT = ROOT / "research/data/liner/gt"
LAPA = ROOT / "research/data/reference/lapa/LaPa/test"
OUT = ROOT / "research/data/liner/eval"
BISENET = ROOT / "research/data/models/bisenet_resnet18.onnx"
# CelebAMask-HQ: 4 left eye, 5 right eye, 6 eye-glass.
CELEB_EYE = (4, 5, 6)
# LaPa: 5 left eye, 6 right eye (official 11-class map).
LAPA_EYE = (5, 6)
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def list_jobs(limit: int):
    jobs = []
    if LINER_IMG.is_dir():
        for p in sorted(LINER_IMG.glob("*.jpg")) + sorted(LINER_IMG.glob("*.png")):
            gt = LINER_GT / (p.stem + ".png")
            jobs.append(("hand", p, gt if gt.is_file() else None, None))
    if LAPA.is_dir() and (LAPA / "images").is_dir():
        names = sorted((LAPA / "images").glob("*.jpg"))
        for p in names:
            lab = LAPA / "labels" / (p.stem + ".png")
            jobs.append(("lapa", p, None, lab if lab.is_file() else None))
    if limit:
        jobs = jobs[:limit]
    return jobs


def eye_from_bisenet(sess, img):
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(cv2.resize(img, (512, 512), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = ((rgb.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)[None]
    t0 = time.perf_counter()
    cls = sess.run(None, {"input": x})[0][0].argmax(0)
    ms = (time.perf_counter() - t0) * 1000
    eye = np.zeros_like(cls, np.uint8)
    for c in CELEB_EYE:
        eye |= (cls == c).astype(np.uint8)
    eye = cv2.resize(eye, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
    return eye, ms


def rim_from_eye(eye, width: int = 4):
    """Thin band around the labeled eye (proxy for lid line until hand masks exist)."""
    u = eye.astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (width * 2 + 1, width * 2 + 1))
    dil = cv2.dilate(u, k)
    ero = cv2.erode(u, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return (dil > 0) & (ero == 0)


def metrics(pred, gt):
    if gt is None or gt.sum() == 0:
        return {}
    inter = (pred & gt).sum()
    union = (pred | gt).sum()
    return {
        "iou": float(inter / max(union, 1)),
        "spill": float((pred & ~gt).sum() / max(pred.sum(), 1)),
        "miss": float((gt & ~pred).sum() / max(gt.sum(), 1)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--frontal-min", type=float, default=0.6)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = list_jobs(args.limit)
    summary = {
        "n": 0,
        "skipped": [],
        "hand_iou_mean": None,
        "hand_spill_mean": None,
        "rim_iou_mean": None,
        "rim_spill_mean": None,
        "lapa_spill_mean": None,
        "bisenet_inside_mean": None,
        "note": "Stroke uses MediaPipe eyelid points. BiSeNet eye class is the whole eye, not a liner stroke.",
    }
    if not jobs:
        summary["skipped"].append("no images in research/data/liner/images or LaPa test")
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return
    if not MODEL.is_file():
        summary["skipped"].append(f"missing {MODEL}")
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return

    landmarker = make_landmarker()
    sess = None
    if BISENET.is_file():
        import onnxruntime as ort

        sess = ort.InferenceSession(str(BISENET), providers=["CPUExecutionProvider"])
    else:
        summary["skipped"].append("no BiSeNet onnx; inside-eye ratio not computed")

    rows = []
    hand_iou, hand_spill, rim_iou, rim_spill, lapa_spill, inside = [], [], [], [], [], []
    for src, path, gt_path, lapa_path in jobs:
        img = cv2.imread(str(path))
        if img is None:
            continue
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not res.face_landmarks:
            continue
        lms = res.face_landmarks[0]
        pts = np.array([[l.x * w, l.y * h] for l in lms])
        front = frontal_score(pts)
        if front < args.frontal_min:
            continue
        pred = stroke_mask(lms, w, h)
        row = {"name": path.stem, "src": src, "pred_px": int(pred.sum()), "frontal": front}
        if gt_path is not None:
            gt = cv2.imread(str(gt_path), cv2.IMREAD_GRAYSCALE)
            if gt is not None:
                gt = cv2.resize(gt, (w, h), interpolation=cv2.INTER_NEAREST) > 127
                m = metrics(pred, gt)
                row.update({f"hand_{k}": v for k, v in m.items()})
                if m:
                    hand_iou.append(m["iou"])
                    hand_spill.append(m["spill"])
        if lapa_path is not None:
            lab = cv2.imread(str(lapa_path), cv2.IMREAD_UNCHANGED)
            if lab is not None:
                lab = lab[..., 0] if lab.ndim == 3 else lab
                eye = np.zeros(lab.shape, bool)
                for c in LAPA_EYE:
                    eye |= lab == c
                row["lapa_inside"] = float(pred[eye].sum() / max(pred.sum(), 1)) if pred.sum() else 0.0
                spill = float(pred[~eye].sum() / max(pred.sum(), 1)) if pred.sum() else 0.0
                row["lapa_spill"] = spill
                lapa_spill.append(spill)
                rim = rim_from_eye(eye)
                m = metrics(pred, rim)
                row.update({f"rim_{k}": v for k, v in m.items()})
                if m:
                    rim_iou.append(m["iou"])
                    rim_spill.append(m["spill"])
        if sess is not None:
            eye, ms = eye_from_bisenet(sess, img)
            ins = float(pred[eye].sum() / max(pred.sum(), 1)) if pred.sum() else 0.0
            row["bisenet_inside"] = ins
            row["bisenet_ms"] = ms
            inside.append(ins)
        rows.append(row)

    summary["n"] = len(rows)
    if hand_iou:
        summary["hand_iou_mean"] = float(np.mean(hand_iou))
        summary["hand_spill_mean"] = float(np.mean(hand_spill))
    else:
        summary["skipped"].append("no hand masks in research/data/liner/gt")
    if rim_iou:
        summary["rim_iou_mean"] = float(np.mean(rim_iou))
        summary["rim_spill_mean"] = float(np.mean(rim_spill))
    if lapa_spill:
        summary["lapa_spill_mean"] = float(np.mean(lapa_spill))
    if inside:
        summary["bisenet_inside_mean"] = float(np.mean(inside))
    if rows:
        with open(OUT / "liner.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
