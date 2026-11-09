"""Compare FaRL face parsing against LaPa labels on a CUDA GPU."""
import argparse
import csv
import json
import time
from pathlib import Path

import cv2
import numpy as np

from metrics_a import measure
from segformer_lapa import pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--variant", choices=("lapa", "celebm"), default="lapa")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--detector-max-side", type=int, default=640,
                        help="Resize only the detector input; coordinates are restored to original pixels")
    args = parser.parse_args()
    if args.limit < 0 or args.detector_max_side <= 0:
        parser.error("--limit must be nonnegative and --detector-max-side positive")

    import facer
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    paths = pairs(args.dataset)
    if args.limit:
        paths = paths[:args.limit]
    device = "cuda"
    detector = facer.face_detector("retinaface/mobilenet", device=device)
    model = facer.face_parser(f"farl/{args.variant}/448", device=device)
    if not {"ulip", "llip"}.issubset(model.label_names):
        raise ValueError(f"Unexpected label mapping: {model.label_names}")
    lip_ids = [model.label_names.index("ulip"), model.label_names.index("llip")]
    rows = []
    for index, (name, image_path, label_path) in enumerate(paths):
        rgb = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        labels = cv2.imread(str(label_path), cv2.IMREAD_UNCHANGED)
        if rgb is None or labels is None or rgb.shape[:2] != labels.shape:
            raise ValueError(f"Invalid image or mask: {name}")
        image = facer.hwc2bchw(torch.from_numpy(cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB))).to(device)
        h, w = rgb.shape[:2]
        scale = min(1.0, args.detector_max_side / max(h, w))
        detect_w, detect_h = max(1, round(w * scale)), max(1, round(h * scale))
        if (detect_w, detect_h) != (w, h):
            small = cv2.resize(rgb, (detect_w, detect_h), interpolation=cv2.INTER_AREA)
            detector_image = facer.hwc2bchw(torch.from_numpy(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))).to(device)
        else:
            detector_image = image
        gt = np.isin(labels, (7, 9))
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            faces = detector(detector_image)
        torch.cuda.synchronize()
        detect_ms = (time.perf_counter() - start) * 1000
        count = len(faces["rects"])
        if count:
            factors = torch.tensor([w / detect_w, h / detect_h], device=device)
            faces["rects"] = faces["rects"] * factors.repeat(2)
            faces["points"] = faces["points"] * factors
        pred = np.zeros(gt.shape, dtype=bool)
        parser_ms = None
        if count:
            rects = faces["rects"]
            areas = (rects[:, 2] - rects[:, 0]).clamp(min=0) * (rects[:, 3] - rects[:, 1]).clamp(min=0)
            chosen = int(areas.argmax().item())
            # Detector returns one row per face in these fields.
            selected = {k: v[chosen:chosen + 1] if isinstance(v, torch.Tensor) and v.ndim and v.shape[0] == count else v for k, v in faces.items()}
            torch.cuda.synchronize()
            start = time.perf_counter()
            with torch.inference_mode():
                result = model(image, selected)
            torch.cuda.synchronize()
            parser_ms = (time.perf_counter() - start) * 1000
            pred = np.isin(result["seg"]["logits"].argmax(dim=1)[0].cpu().numpy(), lip_ids)
        x = np.where(gt)[1]
        width = int(x.max() - x.min() + 1) if x.size else None
        rows.append({"id": name, "faces_detected": count, "gt_pixels": int(gt.sum()),
                     "pred_pixels": int(pred.sum()), "detector_ms": round(detect_ms, 3),
                     "parser_ms": round(parser_ms, 3) if parser_ms is not None else None,
                     **measure(pred, gt, width)})
        if (index + 1) % 20 == 0:
            print(f"{index + 1}/{len(paths)}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    valid = [r for r in rows if r["gt_pixels"] > 0]
    summary = {"model": f"farl/{args.variant}/448", "gpu": torch.cuda.get_device_name(0),
               "torch": torch.__version__, "total": len(rows), "empty_gt": len(rows) - len(valid),
               "no_face": sum(r["faces_detected"] == 0 for r in rows),
               "multi_face": sum(r["faces_detected"] > 1 for r in rows),
               "iou_median_nonempty_gt": float(np.median([r["iou"] for r in valid])) if valid else None,
               "detector_max_side": args.detector_max_side,
               "note": "largest detected face selected; detector resizes input; inference times include first-run warmup; LaPa-trained variant is not cross-dataset"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
