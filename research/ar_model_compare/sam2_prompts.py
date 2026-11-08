"""Generate reproducible SAM 2 lip prompts from app-compatible MediaPipe lip rings.

Input: image width/height, outer and inner lip polygon coordinates in image pixels.
Output: box plus positive/negative points; contains no model inference.
Run tests: research/ar_evaluation/.venv/Scripts/python.exe -m unittest discover -s research/ar_model_compare -p 'test_*.py'
"""
import cv2
import numpy as np


def make_prompts(outer, inner, shape):
    h, w = shape
    outer, inner = np.asarray(outer, np.float32), np.asarray(inner, np.float32)
    if outer.shape != (20, 2) or inner.shape != (20, 2) or not np.isfinite(outer).all() or not np.isfinite(inner).all():
        raise ValueError("expected two finite 20-point app lip rings")
    if h <= 0 or w <= 0:
        raise ValueError("invalid image shape")
    lip = np.zeros((h, w), np.uint8)
    mouth = np.zeros_like(lip)
    cv2.fillPoly(lip, [np.rint(outer).astype(np.int32)], 1)
    cv2.fillPoly(mouth, [np.rint(inner).astype(np.int32)], 1)
    lip[mouth > 0] = 0
    if not lip.any():
        raise ValueError("lip polygon has no interior")
    # Find one robust interior point per half; closed mouths need not have an inner-mouth negative.
    yy, xx = np.indices(lip.shape)
    mid = float(np.median(inner[:, 1]))
    points, labels = [], []
    for region in (lip & (yy < mid), lip & (yy >= mid)):
        if not region.any():
            continue
        distance = cv2.distanceTransform(region.astype(np.uint8), cv2.DIST_L2, 5)
        y, x = np.unravel_index(np.argmax(distance), distance.shape)
        points.append([float(x), float(y)]); labels.append(1)
    if not points:
        raise ValueError("no positive lip prompt")
    if mouth.sum() >= 4:
        distance = cv2.distanceTransform(mouth, cv2.DIST_L2, 5)
        y, x = np.unravel_index(np.argmax(distance), distance.shape)
        points.append([float(x), float(y)]); labels.append(0)
    lo, hi = outer.min(axis=0), outer.max(axis=0)
    margin = max(2.0, 0.08 * float(hi[0] - lo[0]))
    box = [max(0.0, float(lo[0] - margin)), max(0.0, float(lo[1] - margin)),
           min(float(w-1), float(hi[0] + margin)), min(float(h-1), float(hi[1] + margin))]
    # Add outside negatives only when they are actually in-frame and outside the lip outline.
    center_x = float(np.clip((lo[0]+hi[0])/2, 0, w-1))
    for y in (int(np.floor(box[1])), int(np.ceil(box[3]))):
        x = int(round(center_x))
        if 0 <= y < h and not lip[y, x] and not mouth[y, x]:
            points.append([float(x), float(y)]); labels.append(0)
    return {"box": box, "points": points, "labels": labels}
