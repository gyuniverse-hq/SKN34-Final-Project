"""Fit existing blush controls on one video pair; never changes app settings.

One held-out angle is unavailable. Results are candidates, not accepted profiles.
The original product colour is read from the real app hook's exported state.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from playwright.sync_api import sync_playwright

from analyze_blush import calibrate_background, linear, points, read_rgb, srgb, warp_mesh

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/karina_look"
HELPER = ROOT / "research/lip_texture/render.py"
CHEEKS = ([50, 101, 116, 117, 118, 123, 187, 205, 207],
          [280, 330, 345, 346, 347, 352, 411, 425, 427])


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Missing helper {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation", action="store_true", help="use the separate, turned 34s input and 41s target")
    parser.add_argument("--extended", action="store_true", help="search additional blush radii")
    args = parser.parse_args()
    if args.validation and args.extended:
        parser.error("--validation and --extended are separate runs")
    out = DATA / ("blush_angle_validation" if args.validation else "blush_fit_extended" if args.extended else "blush_fit_exploratory")
    OUT = out
    OUT.mkdir(parents=True, exist_ok=True)
    helper = load_module("offline_render", HELPER)
    metrics = load_module("color_metrics", ROOT / "research/lip_texture/metrics.py")
    html = (DATA / "page.html").read_text(encoding="utf-8")
    marker = "const TUNING = {"
    if html.count(marker) != 1:
        raise RuntimeError("Cannot expose research-only tuning")
    html = html.replace(marker, "const TUNING = window.__TUNING = {")
    face = (DATA / ("blush_candidates/0010.png" if args.validation else "blush_candidates/0012.png")).read_bytes()
    setting = json.loads((DATA / "app_makeup.json").read_text(encoding="utf-8"))["makeup"]["blush"]
    if not setting:
        raise RuntimeError("The app hook did not resolve blush")
    cases = [{"name": "app_default", "setting": setting}]
    for intensity in ((0.55,) if args.validation else (0.25, 0.35, 0.55, 0.65, 0.75, 0.85)):
        cases.append({"name": f"default_{intensity:.2f}", "setting": {**setting, "intensity": intensity}})
    for position in (("side",) if args.validation else ("apple", "under_eye", "side")):
        for intensity in ((0.45,) if args.validation else (0.45, 0.65, 0.85)):
            cases.append({"name": f"{position}_{intensity:.2f}",
                          "setting": {**setting, "intensity": intensity,
                                      "geometry": {"blushPlacement": position}}})
    if args.extended:
        for position in ("apple", "under_eye", "side"):
            for size in (1.2, 1.6, 2.0):
                for intensity in (0.45, 0.65):
                    cases.append({"name": f"{position}_size{size:.1f}_{intensity:.2f}",
                                  "setting": {**setting, "intensity": intensity,
                                              "geometry": {"blushPlacement": position, "blushSize": size}}})
    if any(c["setting"]["hex"] != setting["hex"] for c in cases):
        raise RuntimeError("Product colour changed")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                     args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        try:
            ctx = browser.new_context(viewport={"width": 996, "height": 560}, ignore_https_errors=True)
            page = ctx.new_page()
            page.route("**/*", lambda route: route.abort())
            helper.routes(page, face, html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto("https://localhost/")
            helper.wait_status(page, "tracking")
            time.sleep(6)
            # Same page and still camera for every candidate. Freeze scene estimation
            # as in lip_texture/render.py; tracking can still have small jitter.
            page.evaluate("""() => Object.assign(window.__TUNING, {
                lightEveryMs: 1e12, segmentEveryMs: 1e12, segmentEveryMsAuto: 1e12
            })""")
            time.sleep(2)
            helper.shot(page, OUT / "off.png")
            for seq, case in enumerate(cases, start=1):
                makeup = {zone: None for zone in (
                    "lip", "blush", "eyeshadow", "eyeliner", "mascara", "highlighter", "contour", "brow", "foundation"
                )}
                makeup["blush"] = case["setting"]
                page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                              {"type": "makeup", "stateSeq": seq, "makeup": makeup})
                time.sleep(1.5)
                helper.shot(page, OUT / f"{case['name']}.png")
                print("rendered", case["name"], flush=True)
            ctx.close()
        finally:
            browser.close()

    before = read_rgb(OUT / "off.png")
    target = read_rgb(DATA / ("blush_candidates/0024.png" if args.validation else "blush_candidates/0026.png"))
    target = cv2.flip(cv2.resize(target, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA), 1)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")), num_faces=1
    )
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        src_pts, target_pts = points(detector, before), points(detector, target)
    corrected, calibration = calibrate_background(before, target)
    target_warped, coverage = warp_mesh(corrected, target_pts, src_pts, before.shape[:2])
    mask = np.zeros(before.shape[:2], np.uint8)
    for indices in CHEEKS:
        cv2.fillConvexPoly(mask, cv2.convexHull(np.round(src_pts[indices]).astype(np.int32)), 1)
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
    ratio = (mask & coverage).sum() / max(mask.sum(), 1)
    mask &= coverage
    if args.validation:
        # Only the source's screen-left cheek is unobscured in the turned frame;
        # the other cheek is covered by the mirror. Exclude hands and brush via
        # the existing face-skin model in both images and warp the target mask.
        options = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/selfie_multiclass.tflite")),
            output_category_mask=True, output_confidence_masks=False,
        )
        with vision.ImageSegmenter.create_from_options(options) as segmenter:
            def skin(rgb):
                result = segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
                return (result.category_mask.numpy_view().squeeze() == 3).astype(np.float32)
            src_skin, target_skin = skin(before), skin(target)
        warped_skin, skin_coverage = warp_mesh(np.repeat(target_skin[:, :, None], 3, axis=2),
                                              target_pts, src_pts, before.shape[:2])
        skin_intersection = (src_skin > 0.5) & (warped_skin[:, :, 0] > 0.95) & skin_coverage
        skin_intersection = cv2.erode(skin_intersection.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        xx = np.indices(mask.shape)[1]
        mask &= skin_intersection & (xx < (src_pts[33, 0] + src_pts[263, 0]) / 2)
    if mask.sum() < 100 or ratio < 0.95:
        raise RuntimeError("Insufficient cheek coverage")
    cv2.imwrite(str(OUT / "evaluation_mask.png"), mask.astype(np.uint8) * 255)
    cv2.imwrite(str(OUT / "reference_aligned.png"),
                cv2.cvtColor(np.round(srgb(target_warped) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    lab_before = metrics.lab_of(linear(before))
    lab_target = metrics.lab_of(target_warped)
    target_delta = lab_target[mask].mean(axis=0) - lab_before[mask].mean(axis=0)
    light = lab_before[:, :, 0].astype(np.float32)
    base_fine = float((light - cv2.GaussianBlur(light, (0, 0), 1.5))[mask].std())
    rows = []
    for case in cases:
        candidate = read_rgb(OUT / f"{case['name']}.png")
        lab = metrics.lab_of(linear(candidate))
        de = float(np.mean([metrics.de2000(a, b) for a, b in zip(lab[mask], lab_target[mask], strict=True)]))
        candidate_delta = lab[mask].mean(axis=0) - lab_before[mask].mean(axis=0)
        delta_mismatch = float(np.linalg.norm(candidate_delta - target_delta))
        light = lab[:, :, 0].astype(np.float32)
        texture_gap = abs(float((light - cv2.GaussianBlur(light, (0, 0), 1.5))[mask].std()) - base_fine)
        rows.append({"candidate": case["name"], "delta_e2000": de, "delta_lab_mismatch": delta_mismatch,
                     "texture_gap": texture_gap, "objective": de + 0.25 * delta_mismatch + 0.1 * texture_gap,
                     "validation_pair": bool(args.validation)})
    with (OUT / "candidate_metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "run_info.json").write_text(json.dumps({
        "cases": cases, "calibration": calibration, "face_mesh_coverage": ratio,
        "source_s": 34 if args.validation else 35, "target_s": 41 if args.validation else 42,
        "validation_pair": bool(args.validation), "mask_pixels": int(mask.sum()),
        "caveat": "same edited video; skin mask may miss occlusions" if args.validation else "single training pair",
        "status": "candidates_only_not_for_app",
    }, indent=2), encoding="utf-8")
    print("Different-angle video check" if args.validation else "Exploratory fitting; separate angle check required.")
    for row in sorted(rows, key=lambda r: r["objective"]):
        print(row["candidate"], round(row["objective"], 3), "deltaE", round(row["delta_e2000"], 3))


if __name__ == "__main__":
    main()
