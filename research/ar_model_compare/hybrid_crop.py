"""Measure a MediaPipe-guided BiSeNet mouth-crop experiment on local prepared photos.

Input: fixed manifest, existing face polygon JSON and verified local BiSeNet ONNX.
Output: masks, input tensors and CSV under research/data/ar_model_compare/a/hybrid_cpu/.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/hybrid_crop.py
The ONNX input is fixed at 512: 128/192/256 are crop sampling resolutions, then upscaled.
"""
import csv
import hashlib
import json
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort
from mediapipe.tasks.python import BaseOptions, vision

from metrics_a import measure
from run_a import app_ring

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/ar_model_compare"
FACES = ROOT / "research/data/lip_texture/faces"
MODEL = ROOT / "research/bisenet_cuda/models/bisenet-resnet18.onnx"
EXPECTED_SHA256 = "0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f"
SIZES = (128, 192, 256)


def geometry(points, mouth_width):
    """Square centered on the outer-lip bounding box, width 1.6 × mouth width."""
    xy = np.asarray(points, dtype=np.float64)
    if xy.ndim != 2 or xy.shape[1] != 2 or not np.isfinite(xy).all() or mouth_width <= 0:
        raise ValueError("invalid lip points or width")
    side = float(mouth_width) * 1.6
    center = (xy.min(axis=0) + xy.max(axis=0)) / 2
    return float(center[0] - side / 2), float(center[1] - side / 2), side


def sample(image, box, resolution):
    x, y, side = box
    matrix = np.array([[resolution/side, 0, -x*resolution/side], [0, resolution/side, -y*resolution/side]], np.float64)
    return cv2.warpAffine(image, matrix, (resolution, resolution), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def restore(mask, box, shape):
    x, y, side = box
    height, width = shape
    s = mask.shape[0]
    transform = np.array([[side/s, 0, x], [0, side/s, y]], np.float64)
    return cv2.warpAffine(mask.astype(np.uint8), transform, (width, height), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)


def tensor(crop):
    rgb = cv2.cvtColor(cv2.resize(crop, (512, 512), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    rgb = (rgb - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])


def main():
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("BiSeNet checksum differs from recorded model; refusing assumed class map")
    out = DATA / "a/hybrid_cpu"; out.mkdir(parents=True, exist_ok=True)
    with (DATA / "set/manifest.csv").open(encoding="utf-8", newline="") as f:
        items = list(csv.DictReader(f))
    options = ort.SessionOptions(); options.intra_op_num_threads = 1; options.inter_op_num_threads = 1
    net = ort.InferenceSession(str(MODEL), sess_options=options, providers=["CPUExecutionProvider"])
    landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")), num_faces=1))
    outer_indices = app_ring("LIPS_OUTER")
    rows = []
    for item in items:
        img = cv2.imread(str(ROOT / item["path"]))
        if img is None:
            raise FileNotFoundError(item["path"])
        saved = FACES / (item["id"] + ".json")
        if item["source"] == "cc_faces" and saved.is_file():
            info = json.loads(saved.read_text(encoding="utf-8"))
        else:
            rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            detected = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not detected.face_landmarks:
                print(f"no face: {item['id']}", flush=True)
                continue
            h, w = img.shape[:2]
            pts = np.array([(p.x*w, p.y*h) for p in detected.face_landmarks[0]])
            info = {"outer": pts[outer_indices], "mouthWidthPx": float(np.linalg.norm(pts[61]-pts[291]))}
        box = geometry(info["outer"], info["mouthWidthPx"])
        truth = None
        if item.get("gt_path"):
            labels = cv2.imread(str(ROOT / item["gt_path"]), cv2.IMREAD_GRAYSCALE)
            if labels is None or labels.shape != img.shape[:2]:
                raise ValueError(f"invalid ground truth for {item['id']}")
            if item["source"] != "lapa":
                raise ValueError(f"unknown ground truth mapping for {item['source']}")
            truth = np.isin(labels, [7, 9])
        for size in SIZES:
            crop = sample(img, box, size)
            array = tensor(crop)
            array.tofile(out / f"{item['id']}__{size}.f32")
            # The first invocation includes setup; each measured input receives one warmup.
            net.run(None, {net.get_inputs()[0].name: array})
            start = time.perf_counter(); result = net.run(None, {net.get_inputs()[0].name: array})[0]; ms = 1000 * (time.perf_counter()-start)
            labels = result[0].argmax(axis=0).astype(np.uint8)
            mask = np.isin(labels, [12, 13]).astype(np.uint8) * 255
            restored = restore(mask, box, img.shape[:2])
            cv2.imwrite(str(out / f"{item['id']}__{size}__lip.png"), restored)
            scores = measure(restored > 0, truth, info["mouthWidthPx"]) if truth is not None else {}
            rows.append({"id": item["id"], "sampling_px": size, "network_px": 512, "inference_ms": round(ms, 3),
                         "lip_pixels": int((restored > 0).sum()), "iou": scores.get("iou"),
                         "boundary_px": scores.get("boundary_px"), "source": item["source"]})
            print(item["id"], size, round(ms, 1), "ms", flush=True)
    landmarker.close()
    if not rows:
        raise RuntimeError("no images could be processed")
    with (out / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    print("Missing GT produces empty IoU/boundary; masks use CelebAMask-HQ classes 12/13.")


if __name__ == "__main__":
    main()
