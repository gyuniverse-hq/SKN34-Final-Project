"""Exploratory cheek comparison with background colour calibration and landmark warping.

The 35 s and 42 s frames bracket the first cheek product, but video edits,
compression, hand occlusion outside the cheeks and unknown camera processing
prevent this from being a physical product measurement or hold-out validation.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "karina_look"
OUT = DATA / "blush_baseline"
CHEEKS = ([50, 101, 116, 117, 118, 123, 187, 205, 207],
          [280, 330, 345, 346, 347, 352, 411, 425, 427])


def linear(rgb: np.ndarray) -> np.ndarray:
    x = rgb.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055)


def read_rgb(path: Path) -> np.ndarray:
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


def points(detector: vision.FaceLandmarker, rgb: np.ndarray) -> np.ndarray:
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not result.face_landmarks:
        raise RuntimeError("Landmarks were not detected in a candidate frame")
    h, w = rgb.shape[:2]
    return np.array([(p.x * w, p.y * h) for p in result.face_landmarks[0]], dtype=np.float32)


def calibrate_background(source: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, dict]:
    """Fit channel gains/offsets on corresponding background, and report held-out RMSE."""
    h, w = source.shape[:2]
    background = np.zeros((h, w), np.uint8)
    background[:int(h * 0.55), :int(w * 0.17)] = 255
    background[:int(h * 0.55), int(w * 0.85):] = 255
    orb = cv2.ORB_create(nfeatures=3000, fastThreshold=3)
    src_key, src_desc = orb.detectAndCompute(source, background)
    ref_key, ref_desc = orb.detectAndCompute(reference, background)
    if src_desc is None or ref_desc is None:
        raise RuntimeError("Not enough unchanged background to calibrate")
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ref_desc, src_desc, k=2)
    matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.78 * b.distance]
    if len(matches) < 12:
        raise RuntimeError("Not enough background feature matches to calibrate")
    homography, inliers = cv2.findHomography(
        np.float32([ref_key[m.queryIdx].pt for m in matches]),
        np.float32([src_key[m.trainIdx].pt for m in matches]), cv2.RANSAC, 3,
    )
    if homography is None or inliers is None or int(inliers.sum()) < 12:
        raise RuntimeError("Background registration failed")
    aligned = cv2.warpPerspective(linear(reference), homography, (w, h))
    valid = cv2.warpPerspective(np.ones((h, w), np.uint8), homography, (w, h), flags=cv2.INTER_NEAREST) > 0
    dst = linear(source)
    valid &= background > 0
    valid &= ((aligned > 0.005) & (aligned < 0.92) & (dst > 0.005) & (dst < 0.92)).all(axis=2)
    yy, xx = np.indices((h, w))
    train = valid & ((xx + yy) % 5 != 0)
    test = valid & ((xx + yy) % 5 == 0)
    if train.sum() < 500 or test.sum() < 100:
        raise RuntimeError("Too few valid background pixels for calibration")
    corrected = np.empty_like(aligned)
    coeffs, rmses = [], []
    for c in range(3):
        design = np.stack([aligned[:, :, c][train], np.ones(train.sum())], axis=1)
        gain, offset = np.linalg.lstsq(design, dst[:, :, c][train], rcond=None)[0]
        if not (0.5 <= gain <= 2 and -0.15 <= offset <= 0.15):
            raise RuntimeError("Unphysical background calibration; no score produced")
        corrected[:, :, c] = linear(reference)[:, :, c] * gain + offset
        residual = aligned[:, :, c][test] * gain + offset - dst[:, :, c][test]
        coeffs.append([float(gain), float(offset)])
        rmses.append(float(np.sqrt(np.mean(residual ** 2))))
    return np.clip(corrected, 0, 1), {
        "background_matches": len(matches), "background_inliers": int(inliers.sum()),
        "training_pixels": int(train.sum()), "validation_pixels": int(test.sum()),
        "rgb_gain_offset": coeffs, "background_validation_rmse_linear_rgb": rmses,
    }


def warp_mesh(reference: np.ndarray, src: np.ndarray, dst: np.ndarray, shape: tuple[int, int]):
    """Map reference into source geometry using the detected face landmarks."""
    h, w = shape
    subdiv = cv2.Subdiv2D((0, 0, w, h))
    unique = {}
    for i, p in enumerate(dst):
        key = (int(round(float(p[0]))), int(round(float(p[1]))))
        if 0 <= key[0] < w and 0 <= key[1] < h and key not in unique:
            unique[key] = i
            subdiv.insert((float(key[0]), float(key[1])))
    keys = np.array(list(unique), np.float32)
    ids = list(unique.values())
    warped = np.zeros((h, w, 3), np.float32)
    covered = np.zeros((h, w), np.uint8)
    for tri in subdiv.getTriangleList():
        vertices = np.array(tri, np.float32).reshape(3, 2)
        nearest = np.linalg.norm(keys[:, None, :] - vertices[None, :, :], axis=2)
        closest = np.argmin(nearest, axis=0)
        if (nearest[closest, np.arange(3)] > 1.5).any():
            continue
        indices = [ids[i] for i in closest]
        a, b = src[indices], dst[indices]
        if len(set(indices)) < 3 or abs(cv2.contourArea(a)) < 0.5:
            continue
        # Landmarks can lie beyond a cropped video frame. Do not fill those
        # triangles with the black border returned by warpAffine.
        if (a[:, 0] < 0).any() or (a[:, 0] >= w).any() or (a[:, 1] < 0).any() or (a[:, 1] >= h).any():
            continue
        x, y, tw, th = cv2.boundingRect(b)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + tw), min(h, y + th)
        if x1 <= x0 or y1 <= y0:
            continue
        local = b - [x0, y0]
        transform = cv2.getAffineTransform(a.astype(np.float32), local.astype(np.float32))
        patch = cv2.warpAffine(reference, transform, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
        mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(mask, np.round(local).astype(np.int32), 1)
        select = mask > 0
        warped[y0:y1, x0:x1][select] = patch[select]
        covered[y0:y1, x0:x1][select] = 1
    return warped, covered > 0


def main() -> None:
    source, ar = read_rgb(OUT / "off.png"), read_rgb(OUT / "blush.png")
    target = read_rgb(DATA / "blush_candidates/0026.png")
    target = cv2.flip(cv2.resize(target, (source.shape[1], source.shape[0]), interpolation=cv2.INTER_AREA), 1)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")),
        num_faces=1,
    )
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        source_pts, target_pts = points(detector, source), points(detector, target)
    corrected, calibration = calibrate_background(source, target)
    target_warped, coverage = warp_mesh(corrected, target_pts, source_pts, source.shape[:2])
    mask = np.zeros(source.shape[:2], np.uint8)
    for indices in CHEEKS:
        cv2.fillConvexPoly(mask, cv2.convexHull(np.round(source_pts[indices]).astype(np.int32)), 1)
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
    coverage_ratio = float((mask & coverage).sum() / max(mask.sum(), 1))
    mask &= coverage
    if mask.sum() < 100 or coverage_ratio < 0.95:
        raise RuntimeError("Insufficient cheek coverage after warping")
    spec = importlib.util.spec_from_file_location("lip_metrics", ROOT / "research/lip_texture/metrics.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing existing colour metrics")
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    lab_base, lab_ar, lab_target = [metrics.lab_of(x) for x in (linear(source), linear(ar), target_warped)]
    distance = np.array([metrics.de2000(a, b) for a, b in zip(lab_ar[mask], lab_target[mask], strict=True)])
    summary = {
        "kind": "exploratory_not_validated_product_measurement",
        "source_seconds": 35, "target_seconds": 42,
        "calibration": calibration, "cheek_pixels": int(mask.sum()), "mesh_coverage": coverage_ratio,
        "mean_delta_e2000_ar_vs_video": float(distance.mean()),
        "ar_mean_delta_lab_from_source": (lab_ar[mask].mean(axis=0) - lab_base[mask].mean(axis=0)).tolist(),
        "video_mean_delta_lab_from_source": (lab_target[mask].mean(axis=0) - lab_base[mask].mean(axis=0)).tolist(),
    }
    for name, lab in (("before", lab_base), ("ar", lab_ar), ("video", lab_target)):
        lightness = lab[:, :, 0].astype(np.float32)
        high_frequency = lightness - cv2.GaussianBlur(lightness, (0, 0), 1.5)
        summary[f"{name}_lstar_p90_p10"] = float(np.percentile(lightness[mask], 90) - np.percentile(lightness[mask], 10))
        summary[f"{name}_lstar_highpass_std"] = float(high_frequency[mask].std())
    (OUT / "exploratory_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (OUT / "metrics_baseline.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["region", "metric", "value", "status"])
        writer.writerow(["blush", "mean_delta_e2000_ar_vs_video", summary["mean_delta_e2000_ar_vs_video"], "exploratory_only"])
        for name in ("before", "ar", "video"):
            for metric in ("lstar_p90_p10", "lstar_highpass_std"):
                writer.writerow(["blush", f"{name}_{metric}", summary[f"{name}_{metric}"], "exploratory_only"])
    cv2.imwrite(str(OUT / "target_warped.png"), cv2.cvtColor((srgb(target_warped) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(OUT / "cheek_mask.png"), mask.astype(np.uint8) * 255)
    width = 480
    height = round(source.shape[0] * width / source.shape[1])
    sheet = Image.new("RGB", (width * 3, height + 30), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, rgb) in enumerate((("before_35s", source), ("ar_blush_35s", ar), ("video_42s_unwarped", target))):
        sheet.paste(Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS), (i * width, 0))
        draw.text((i * width + 5, height + 5), label, fill="black")
    sheet.save(OUT / "exploratory_comparison.png")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
