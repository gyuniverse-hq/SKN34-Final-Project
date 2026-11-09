"""Evaluate SegFormer face parsing on paired LaPa test images and masks.

Requires torch, transformers, Pillow, numpy and OpenCV. Face data and output
stay under the explicitly selected paths. This is a research-only benchmark.
"""
import argparse
import csv
import json
import time
from pathlib import Path

import cv2
import numpy as np

from metrics_a import measure


def pairs(dataset):
    images = {p.stem: p for p in (dataset / "images").glob("*.jpg")}
    labels = {p.stem: p for p in (dataset / "labels").glob("*.png")}
    if not images or images.keys() != labels.keys():
        raise ValueError("images and labels must contain matching JPG/PNG stems")
    return [(name, images[name], labels[name]) for name in sorted(images)]


def evaluate(args):
    import torch
    import torch.nn.functional as functional
    from PIL import Image
    from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; GPU benchmark requires CUDA")
    samples = pairs(args.dataset)
    if args.limit:
        samples = samples[:args.limit]
    processor = SegformerImageProcessor.from_pretrained(args.model, revision=args.revision)
    model = SegformerForSemanticSegmentation.from_pretrained(args.model, revision=args.revision).cuda().eval()
    labels = {str(v).lower(): int(k) for k, v in model.config.id2label.items()}
    if not {"u_lip", "l_lip"}.issubset(labels):
        raise ValueError(f"Unexpected model class mapping: {labels}")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, (name, image_path, label_path) in enumerate(samples):
        with Image.open(image_path) as f:
            image = f.convert("RGB")
        truth_labels = cv2.imread(str(label_path), cv2.IMREAD_UNCHANGED)
        if truth_labels is None or truth_labels.shape != (image.height, image.width):
            raise ValueError(f"Invalid or mismatched mask for {name}")
        gt = np.isin(truth_labels, [7, 9])
        inputs = processor(images=image, return_tensors="pt").to("cuda")
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            logits = model(**inputs).logits
        torch.cuda.synchronize()
        inference_ms = (time.perf_counter() - started) * 1000
        with torch.inference_mode():
            logits = functional.interpolate(logits, size=(image.height, image.width), mode="bilinear", align_corners=False)
            pred = np.isin(logits.argmax(dim=1)[0].cpu().numpy(), [labels["u_lip"], labels["l_lip"]])
        x = np.where(gt)[1]
        width = int(x.max() - x.min() + 1) if x.size else None
        metrics = measure(pred, gt, width)
        rows.append({"id": name, "gt_pixels": int(gt.sum()), "pred_pixels": int(pred.sum()),
                     "inference_ms": round(inference_ms, 3), **metrics})
        if (idx + 1) % 20 == 0:
            print(f"{idx + 1}/{len(samples)}", flush=True)
    with (args.output / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    valid = [r for r in rows if r["gt_pixels"] > 0]
    summary = {"model": args.model, "revision_requested": args.revision,
               "revision_resolved": getattr(model.config, "_commit_hash", None),
               "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__,
               "total": len(rows), "empty_gt": len(rows) - len(valid),
               "iou_median_nonempty_gt": float(np.median([r["iou"] for r in valid])) if valid else None,
               "timing_note": "forward pass only; first image includes warmup; no preprocessing or transfer"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True, help="LaPa test directory containing images/ and labels/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="First N sorted samples; zero uses all")
    parser.add_argument("--model", default="jonathandinu/face-parsing")
    parser.add_argument("--revision", default="main")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    evaluate(args)


if __name__ == "__main__":
    main()
