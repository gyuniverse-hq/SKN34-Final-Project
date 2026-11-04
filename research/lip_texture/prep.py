"""Crop test faces to a phone selfie frame (720x960) and store the lip polygons.

Inputs: research/data/lip_texture/src/*.jpg (public-licence photos, see SOURCES.tsv; not committed).
Outputs: research/data/lip_texture/faces/<name>.png and <name>.json (outer/inner lip rings in pixels).

Run: research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/prep.py [--face-width 0.55]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_texture"
MODEL = ROOT / "research" / "data" / "models" / "face_landmarker.task"
W, H = 720, 960

LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]


def landmarker() -> vision.FaceLandmarker:
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1)
    return vision.FaceLandmarker.create_from_options(opts)


def detect(lm: vision.FaceLandmarker, rgb: np.ndarray) -> np.ndarray | None:
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.face_landmarks:
        return None
    h, w = rgb.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0]], dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--face-width", type=float, default=0.55, help="face oval width / frame width")
    args = ap.parse_args()
    out = DATA / "faces"
    out.mkdir(parents=True, exist_ok=True)
    lm = landmarker()
    for src in sorted((DATA / "src").glob("*.jpg")):
        bgr = cv2.imread(str(src))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pts = detect(lm, rgb)
        if pts is None:
            print(f"{src.name}: no face")
            continue
        oval = pts[FACE_OVAL]
        fw = float(oval[:, 0].max() - oval[:, 0].min())
        scale = (args.face_width * W) / fw
        cx, cy = float(oval[:, 0].mean()), float(oval[:, 1].mean())
        # Affine: face centre to (W/2, 0.47 H), uniform scale; pad with edge colour where the photo ends.
        m = np.array([[scale, 0, W / 2 - scale * cx], [0, scale, 0.47 * H - scale * cy]], dtype=np.float32)
        crop = cv2.warpAffine(rgb, m, (W, H), flags=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
        pts2 = detect(lm, crop)
        if pts2 is None:
            print(f"{src.name}: no face after crop")
            continue
        lip_w = float(np.linalg.norm(pts2[61] - pts2[291]))
        name = src.stem
        cv2.imwrite(str(out / f"{name}.png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
        (out / f"{name}.json").write_text(json.dumps({
            "outer": pts2[LIPS_OUTER].round(2).tolist(),
            "inner": pts2[LIPS_INNER].round(2).tolist(),
            "mouthWidthPx": round(lip_w, 1),
            "scale": round(scale, 3),
        }))
        print(f"{name}: scale {scale:.2f}, mouth {lip_w:.0f}px")


if __name__ == "__main__":
    main()
