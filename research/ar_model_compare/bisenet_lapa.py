"""Evaluate the checked BiSeNet ONNX model against LaPa lip masks."""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np

from metrics_a import measure
from segformer_lapa import pairs

EXPECTED = "0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    import torch  # load CUDA libraries before ONNX Runtime
    import onnxruntime as ort

    if hashlib.sha256(args.model.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError("Unexpected model checksum")
    if not torch.cuda.is_available() or "CUDAExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError("CUDA and ONNX Runtime GPU provider are required")
    session = ort.InferenceSession(str(args.model), providers=["CUDAExecutionProvider"])
    if session.get_providers()[0] != "CUDAExecutionProvider":
        raise RuntimeError("Failed to activate CUDA provider")
    samples = pairs(args.dataset)
    if args.limit:
        samples = samples[:args.limit]
    rows = []
    for index, (name, image_path, label_path) in enumerate(samples):
        image = cv2.imread(str(image_path))
        label = cv2.imread(str(label_path), cv2.IMREAD_UNCHANGED)
        if image is None or label is None or image.shape[:2] != label.shape:
            raise ValueError(f"Invalid image or mask: {name}")
        h, w = label.shape
        gt = np.isin(label, (7, 9))
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (512, 512)).astype(np.float32) / 255.0
        norm = (resized - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
        tensor = np.ascontiguousarray(norm.transpose(2, 0, 1)[None])
        start = time.perf_counter()
        logits = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
        elapsed_ms = (time.perf_counter() - start) * 1000
        classes = np.argmax(logits, axis=0).astype(np.uint8)
        classes = cv2.resize(classes, (w, h), interpolation=cv2.INTER_NEAREST)
        pred = np.isin(classes, (12, 13))
        x = np.where(gt)[1]
        width = int(x.max() - x.min() + 1) if x.size else None
        rows.append({"id": name, "gt_pixels": int(gt.sum()), "pred_pixels": int(pred.sum()),
                     "inference_ms": round(elapsed_ms, 3), **measure(pred, gt, width)})
        if (index + 1) % 20 == 0:
            print(f"{index + 1}/{len(samples)}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    valid = [r for r in rows if r["gt_pixels"] > 0]
    summary = {"model": "bisenet_r18_onnx", "model_sha256": EXPECTED,
               "gpu": torch.cuda.get_device_name(0), "ort": ort.__version__,
               "providers": session.get_providers(), "total": len(rows),
               "empty_gt": len(rows) - len(valid),
               "iou_median_nonempty_gt": float(np.median([r["iou"] for r in valid])) if valid else None,
               "timing_note": "ONNX Runtime session.run includes CPU/GPU tensor transfer and first-run warmup; excludes preprocessing"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
