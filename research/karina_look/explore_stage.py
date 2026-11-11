"""Align an intermediate makeup stage with the real single-zone AR render.

This is an exploratory video comparison. Landmarks and colour differences are
not a verified product mask, and the brow stage contains multiple products.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageDraw

from analyze_blush import calibrate_background, linear, points, read_rgb, srgb, warp_mesh

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/karina_look"
CASES = {
    "brow": {"before_s": 18, "after_s": 35, "target": "brow_scan/0020.png"},
    "contour": {"before_s": 48, "after_s": 67, "target": "contour_scan/0022.png"},
    "eyeshadow": {"before_s": 67, "after_s": 95, "target": "shadow_scan/0020.png"},
    "eyeliner": {"before_s": 107, "after_s": 119, "target": "liner_scan/0014.png"},
}
EYES = (
    [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
    [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466],
)
BROWS = ([70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
         [300, 293, 334, 296, 336, 285, 295, 282, 283, 276])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", choices=CASES, required=True)
    args = parser.parse_args()
    case = CASES[args.zone]
    out = DATA / f"{args.zone}_baseline"
    before = read_rgb(out / "off.png")
    ar = read_rgb(out / f"{args.zone}.png")
    target = read_rgb(DATA / case["target"])
    target = cv2.flip(cv2.resize(target, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA), 1)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")), num_faces=1
    )
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        before_pts, target_pts = points(detector, before), points(detector, target)
    try:
        corrected, calibration = calibrate_background(before, target)
        calibrated = True
    except RuntimeError as exc:
        corrected, calibration, calibrated = linear(target), {"failure": str(exc)}, False
    warped, coverage = warp_mesh(corrected, target_pts, before_pts, before.shape[:2])
    if args.zone in ("brow", "eyeshadow", "eyeliner"):
        # Broad anatomical regions only. They are not inferred makeup boundaries.
        region = np.zeros(before.shape[:2], np.uint8)
        for indices in (BROWS if args.zone == "brow" else EYES):
            cv2.fillConvexPoly(region, cv2.convexHull(np.round(before_pts[indices]).astype(np.int32)), 1)
        face_width = float(np.linalg.norm(before_pts[234] - before_pts[454]))
        radius = max(2, round(face_width * (0.035 if args.zone == "brow" else 0.08 if args.zone == "eyeshadow" else 0.055)))
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2))
        coverage &= region > 0
    aligned = before.copy()
    aligned[coverage] = np.round(srgb(warped[coverage]) * 255).astype(np.uint8)
    overlay = before.copy()
    overlay[coverage] = np.round(before[coverage] * 0.5 + aligned[coverage] * 0.5).astype(np.uint8)
    for name, rgb in (("video_aligned.png", aligned), ("before_video_overlay.png", overlay)):
        cv2.imwrite(str(out / name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    width = 500
    height = round(before.shape[0] * width / before.shape[1])
    sheet = Image.new("RGB", (width * 4, height + 32), "white")
    draw = ImageDraw.Draw(sheet)
    panels = ((f"before_{case['before_s']}s", before), (f"current_ar_{args.zone}", ar),
              (f"video_{case['after_s']}s_aligned", aligned), ("before_video_overlay", overlay))
    for i, (label, rgb) in enumerate(panels):
        sheet.paste(Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS), (i * width, 0))
        draw.text((i * width + 5, height + 6), label, fill="black")
    sheet.save(out / "stage_comparison.png")
    result = {
        "zone": args.zone, "before_s": case["before_s"], "after_s": case["after_s"],
        "background_color_calibrated": calibrated, "background_calibration": calibration,
        "face_mesh_pixels_covered": int(coverage.sum()),
        "status": "exploratory_not_verified_product_placement",
        "limits": {
            "brow": ["two_brow_products", "pose_and_size_change", "background_calibration_failed"],
            "contour": ["chin_occlusion", "jaw_and_nose_use_different_products", "no_independent_angle"],
            "eyeshadow": ["multiple_eyeshadow_products", "different_gaze", "no_independent_angle"],
            "eyeliner": ["before_already_has_shadow_guide", "target_product_near_eye", "no_independent_angle"],
        }[args.zone],
    }
    (out / "stage_info.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
