"""Run an exploratory CPU-only model smoke test on the manifest, without inventing GT scores.

Input: build_set.py manifest, local Face Landmarker and existing BiSeNet ONNX.
Output: research/data/ar_model_compare/a/smoke/metrics.csv and local mask PNGs.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/run_a.py
BiSeNet's 19-class layout and ImageNet normalization are assumptions, not verified provenance.
"""
import csv
import json
import re
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/ar_model_compare"
MODEL = ROOT / "research/data/models/face_landmarker.task"
ONNX = ROOT / "research/bisenet_cuda/models/bisenet-resnet18.onnx"
PAGE = ROOT / "components/ar/faceTrackerHtml.ts"


def app_ring(name):
    text = PAGE.read_text(encoding="utf-8")
    match = re.search(r"const " + name + r" = (\[[0-9, ]+\]);", text)
    if not match:
        raise ValueError(f"app index array {name} not found")
    return json.loads(match.group(1))


def poly(shape, points):
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.round(points).astype(np.int32)], 255)
    return mask


def run():
    out = DATA / "a/smoke"; out.mkdir(parents=True, exist_ok=True)
    with (DATA / "set/manifest.csv").open(encoding="utf-8", newline="") as f:
        inputs = list(csv.DictReader(f))
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1)
    face = vision.FaceLandmarker.create_from_options(opts)
    net = ort.InferenceSession(str(ONNX), providers=["CPUExecutionProvider"])
    outer, inner = app_ring("LIPS_OUTER"), app_ring("LIPS_INNER")
    rows = []
    for item in inputs:
        img = cv2.imread(str(ROOT / item["path"]))
        if img is None:
            raise FileNotFoundError(item["path"])
        h, w = img.shape[:2]
        rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        start = time.perf_counter(); detected = face.detect(mp_image); ms = (time.perf_counter()-start)*1000
        success = bool(detected.face_landmarks)
        if success:
            pts = np.array([(p.x*w, p.y*h) for p in detected.face_landmarks[0]])
            lip = poly((h,w), pts[outer]); lip[poly((h,w), pts[inner]) > 0] = 0
            cv2.imwrite(str(out / f"{item['id']}__mediapipe_lip.png"), lip)
        rows.append({"id": item["id"], "model": "mediapipe_landmarker", "device": "cpu", "inference_ms": round(ms, 3), "detected": success, "iou": "", "boundary_px": "", "note": "no ground truth; image mode"})
        frame = cv2.resize(rgb, (512,512)).astype(np.float32)/255
        frame = (frame - np.array([.485,.456,.406],np.float32)) / np.array([.229,.224,.225],np.float32)
        tensor = np.ascontiguousarray(frame.transpose(2,0,1)[None])
        start = time.perf_counter(); output = net.run(None, {net.get_inputs()[0].name: tensor}); elapsed = (time.perf_counter()-start)*1000
        # Timing only: model provenance and class mapping are not documented in the local artifact.
        rows.append({"id": item["id"], "model": "bisenet_r18", "device": "cpu", "inference_ms": round(elapsed, 3), "detected": "unverified", "iou": "", "boundary_px": "", "note": f"preprocessing assumed; output shape {list(output[0].shape)}; classes unverified"})
        # The existing renderer captures two different frames; movement and the threshold
        # can contribute false changes. This is a smoke mask, not a segmentation prediction.
        render_dir = ROOT / "research/data/lip_texture/renders/ar_model_compare_b"
        off_path = render_dir / f"{item['id']}__off.png"
        on_path = render_dir / f"{item['id']}__satin_red__current.png"
        if off_path.exists() and on_path.exists():
            off, on = cv2.imread(str(off_path)), cv2.imread(str(on_path))
            change = np.abs(off.astype(np.int16) - on.astype(np.int16)).sum(axis=2) > 24
            cv2.imwrite(str(out / f"{item['id']}__app_render_changed.png"), change.astype(np.uint8) * 255)
            rows.append({"id": item["id"], "model": "app_render", "device": "headless WebGL", "inference_ms": "", "detected": "unverified", "iou": "", "boundary_px": "", "note": "RGB sum change >24; different capture frames and lipstick rendering are confounds; no GT"})
        print(item["id"], "MediaPipe", round(ms, 1), "ms; BiSeNet", round(elapsed, 1), "ms", flush=True)
    face.close()
    with (out / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    summary = {"status": "smoke_only_no_ground_truth", "source": "research/data/ar_model_compare/a/smoke/metrics.csv",
               "providers": ort.get_available_providers(), "comparability": "CPU times include first-run initialization and were not measured on a phone; BiSeNet preprocessing is unverified.",
               "models": {name: {"images": len([r for r in rows if r["model"] == name]),
                                  "inference_ms_median": float(np.median([r["inference_ms"] for r in rows if r["model"] == name]))}
                          for name in ("mediapipe_landmarker", "bisenet_r18")}}
    summary["models"]["app_render"] = {"images": len([r for r in rows if r["model"] == "app_render"]), "inference_ms_median": None}
    result = ROOT / "research/ar_model_compare/results/a_summary.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return rows


if __name__ == "__main__":
    run()
