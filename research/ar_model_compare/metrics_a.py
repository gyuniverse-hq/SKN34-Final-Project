"""Region-mask accuracy and paired-bootstrap primitives for future labelled comparisons.

Input: equal-sized binary prediction and ground-truth masks.
Output: numeric metrics; undefined divisions return None.
Run tests: research/ar_evaluation/.venv/Scripts/python.exe -m unittest discover -s research/ar_model_compare -p 'test_*.py'
"""
import cv2
import numpy as np


def measure(prediction, truth, mouth_width):
    pred = np.asarray(prediction, dtype=bool)
    gt = np.asarray(truth, dtype=bool)
    if pred.shape != gt.shape or pred.ndim != 2:
        raise ValueError("prediction and truth must be same-sized 2D masks")
    n_pred, n_gt = int(pred.sum()), int(gt.sum())
    intersection = int((pred & gt).sum())
    union = n_pred + n_gt - intersection
    result = {"iou": intersection / union if union else None,
              "dice": 2 * intersection / (n_pred + n_gt) if n_pred + n_gt else None,
              "spill": (n_pred - intersection) / n_pred if n_pred else None,
              "miss": (n_gt - intersection) / n_gt if n_gt else None,
              "boundary_px": None, "boundary_mouth_pct": None}
    if n_pred and n_gt:
        def boundary(mask):
            src = mask.astype(np.uint8)
            eroded = cv2.erode(src, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
            return src.astype(bool) & ~eroded.astype(bool)
        a, b = boundary(pred), boundary(gt)
        dist_a = cv2.distanceTransform((~a).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        dist_b = cv2.distanceTransform((~b).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        distance = float((dist_a[b].mean() + dist_b[a].mean()) / 2)
        result["boundary_px"] = distance
        if mouth_width and mouth_width > 0:
            result["boundary_mouth_pct"] = 100 * distance / mouth_width
    return result


def bootstrap_median(values, seed=42, repetitions=2000):
    data = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if not len(data):
        return {"n": 0, "median": None, "ci95": None}
    generator = np.random.default_rng(seed)
    samples = generator.choice(data, size=(repetitions, len(data)), replace=True)
    low, high = np.percentile(np.median(samples, axis=1), [2.5, 97.5])
    return {"n": len(data), "median": float(np.median(data)), "ci95": [float(low), float(high)]}
