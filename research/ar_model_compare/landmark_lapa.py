"""LaPa comparison: MediaPipe lip polygons and SAM 2 prompted by those landmarks.

MediaPipe is a proxy for the app's geometry, not its whole renderer/WebView.
SAM 2 uses only predicted landmarks for prompts, never the ground-truth mask.
"""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np

from metrics_a import measure
from sam2_prompts import make_prompts
from segformer_lapa import pairs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--landmarker", required=True, type=Path)
    p.add_argument("--rings", required=True, type=Path)
    p.add_argument("--mode", choices=("mediapipe", "sam2"), required=True)
    p.add_argument("--sam-checkpoint", type=Path)
    p.add_argument("--sam-config", default="configs/sam2.1/sam2.1_hiera_l.yaml")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    if args.limit < 0 or (args.mode == "sam2" and not args.sam_checkpoint):
        p.error("--limit must be nonnegative; SAM 2 requires --sam-checkpoint")

    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    rings = json.loads(args.rings.read_text(encoding="utf-8"))
    outer_ids, inner_ids = rings["LIPS_OUTER"], rings["LIPS_INNER"]
    if len(outer_ids) != 20 or len(inner_ids) != 20:
        raise ValueError("Expected the 20-point app lip rings")
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(args.landmarker)), num_faces=1)
    detector = vision.FaceLandmarker.create_from_options(opts)
    predictor = None
    if args.mode == "sam2":
        import torch
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        if not torch.cuda.is_available():
            raise RuntimeError("SAM 2 requires CUDA in this benchmark")
        predictor = SAM2ImagePredictor(build_sam2(args.sam_config, str(args.sam_checkpoint), device="cuda"))
    items = pairs(args.dataset)
    if args.limit:
        items = items[:args.limit]
    rows = []
    try:
        for index, (name, image_path, label_path) in enumerate(items):
            image = cv2.imread(str(image_path))
            annotation = cv2.imread(str(label_path), cv2.IMREAD_UNCHANGED)
            if image is None or annotation is None or image.shape[:2] != annotation.shape:
                raise ValueError(f"Invalid image or annotation: {name}")
            h, w = annotation.shape
            gt = np.isin(annotation, (7, 9))
            rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            start = time.perf_counter()
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            face_ms = (time.perf_counter() - start) * 1000
            pred = np.zeros((h, w), dtype=bool)
            model_ms = None
            status = "no_face"
            if result.face_landmarks:
                pts = np.array([(v.x * w, v.y * h) for v in result.face_landmarks[0]])
                outer, inner = pts[outer_ids], pts[inner_ids]
                poly = np.zeros((h, w), np.uint8)
                cv2.fillPoly(poly, [np.rint(outer).astype(np.int32)], 1)
                cv2.fillPoly(poly, [np.rint(inner).astype(np.int32)], 0)
                pred = poly.astype(bool)
                status = "ok"
                if predictor is not None:
                    try:
                        prompts = make_prompts(outer, inner, (h, w))
                    except ValueError:
                        status = "invalid_prompt"
                        pred = np.zeros((h, w), dtype=bool)
                    else:
                        torch.cuda.synchronize()
                        start = time.perf_counter()
                        with torch.inference_mode():
                            predictor.set_image(rgb)
                            masks, scores, _ = predictor.predict(
                                point_coords=np.asarray(prompts["points"], dtype=np.float32),
                                point_labels=np.asarray(prompts["labels"], dtype=np.int32),
                                box=np.asarray(prompts["box"], dtype=np.float32), multimask_output=True)
                        torch.cuda.synchronize()
                        model_ms = (time.perf_counter() - start) * 1000
                        pred = np.asarray(masks[int(np.argmax(scores))], dtype=bool)
            xs = np.where(gt)[1]
            width = int(xs.max() - xs.min() + 1) if xs.size else None
            rows.append({"id": name, "status": status, "gt_pixels": int(gt.sum()),
                         "pred_pixels": int(pred.sum()), "landmarker_ms": round(face_ms, 3),
                         "sam_image_and_prompt_ms": round(model_ms, 3) if model_ms is not None else None,
                         **measure(pred, gt, width)})
            print(f"{index + 1}/{len(items)} {status}", flush=True)
    finally:
        detector.close()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    valid = [r for r in rows if r["gt_pixels"]]
    summary = {"model": args.mode, "total": len(rows), "empty_gt": len(rows) - len(valid),
               "no_face": sum(r["status"] == "no_face" for r in rows),
               "invalid_prompt": sum(r["status"] == "invalid_prompt" for r in rows),
               "iou_median_nonempty_gt": float(np.median([r["iou"] for r in valid])) if valid else None,
               "landmarker_sha256": hashlib.sha256(args.landmarker.read_bytes()).hexdigest(),
               "ring_source": rings.get("source"),
               "note": "MediaPipe Tasks IMAGE mode polygon proxy, not app render; SAM 2 prompts are generated from predicted landmarks and model-selected score; timings include first-run warmup"}
    if args.mode == "sam2":
        summary.update({"gpu": torch.cuda.get_device_name(0), "sam_config": args.sam_config,
                        "checkpoint_sha256": hashlib.sha256(args.sam_checkpoint.read_bytes()).hexdigest()})
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
