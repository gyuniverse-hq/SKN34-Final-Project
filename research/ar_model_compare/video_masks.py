"""Generate comparable lip masks for an explicitly supplied video.

Research-only: output masks are intermediate data, not AR-rendered results.
Every model samples identical decoded frame indices and receives identical RGB.
"""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--model", required=True, choices=("mediapipe", "bisenet", "segformer", "farl-lapa", "farl-celebm", "sam2"))
    p.add_argument("--landmarker", type=Path)
    p.add_argument("--rings", type=Path)
    p.add_argument("--onnx", type=Path)
    p.add_argument("--sam-checkpoint", type=Path)
    p.add_argument("--sam-config", default="configs/sam2.1/sam2.1_hiera_l.yaml")
    p.add_argument("--fps", type=float, default=5)
    p.add_argument("--max-side", type=int, default=960)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda", help="CPU is supported for BiSeNet and MediaPipe")
    args = p.parse_args()
    if args.fps <= 0 or args.max_side <= 0:
        p.error("fps and max-side must be positive")
    torch = None
    if args.device == "cpu" and args.model not in ("bisenet", "mediapipe"):
        p.error("CPU mode is supported only for BiSeNet and MediaPipe")
    if args.model != "mediapipe" and args.device == "cuda":
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA required for this model")
    detector = parser = net = processor = predictor = None
    labels = {}
    meta = {"model": args.model, "requested_fps": args.fps, "max_side": args.max_side,
            "video_sha256": hashlib.sha256(args.video.read_bytes()).hexdigest(),
            "note": "Offline sampled-frame masks; no AR renderer or network latency measured."}
    if args.model in ("mediapipe", "sam2"):
        if not args.rings or not args.landmarker:
            p.error("MediaPipe and SAM 2 require --rings and --landmarker")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        rings = json.loads(args.rings.read_text(encoding="utf8"))
        detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(args.landmarker)), num_faces=1))
        if args.model == "sam2":
            if not args.sam_checkpoint:
                p.error("SAM 2 requires --sam-checkpoint")
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
            from sam2_prompts import make_prompts
            predictor = SAM2ImagePredictor(build_sam2(args.sam_config, str(args.sam_checkpoint), device="cuda"))
            meta["checkpoint_sha256"] = hashlib.sha256(args.sam_checkpoint.read_bytes()).hexdigest()
    elif args.model == "segformer":
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        name = "jonathandinu/face-parsing"
        processor = SegformerImageProcessor.from_pretrained(name)
        net = SegformerForSemanticSegmentation.from_pretrained(name).cuda().eval()
        labels = {str(v).lower(): int(k) for k, v in net.config.id2label.items()}
        meta["revision"] = getattr(net.config, "_commit_hash", None)
    elif args.model == "bisenet":
        if not args.onnx:
            p.error("BiSeNet requires --onnx")
        import onnxruntime as ort
        digest = hashlib.sha256(args.onnx.read_bytes()).hexdigest()
        if digest != "0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f":
            raise ValueError("Unexpected BiSeNet model hash")
        provider = "CUDAExecutionProvider" if args.device == "cuda" else "CPUExecutionProvider"
        net = ort.InferenceSession(str(args.onnx), providers=[provider])
        if net.get_providers()[0] != provider:
            raise RuntimeError(f"ONNX {provider} did not initialize")
        meta.update(model_sha256=digest, providers=net.get_providers(), device=args.device)
    else:
        import facer
        detector = facer.face_detector("retinaface/mobilenet", device="cuda")
        parser = facer.face_parser("farl/" + args.model.split("-", 1)[1] + "/448", device="cuda")
        labels = [parser.label_names.index("ulip"), parser.label_names.index("llip")]
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError("OpenCV could not decode the video")
    source_fps = cap.get(cv2.CAP_PROP_FPS)
    if not np.isfinite(source_fps) or source_fps <= 0 or args.fps > source_fps:
        raise ValueError("Invalid source frame rate or requested FPS exceeds source")
    args.output.mkdir(parents=True, exist_ok=True)
    mask_dir = args.output / "masks"
    mask_dir.mkdir(exist_ok=True)
    rows = []
    frame_i = 0
    sample_i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_i < round(sample_i * source_fps / args.fps):
                frame_i += 1
                continue
            h, w = frame.shape[:2]
            scale = min(1.0, args.max_side / max(h, w))
            if scale < 1:
                frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
            rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if args.model != "mediapipe" and args.device == "cuda":
                torch.cuda.synchronize()
            start = time.perf_counter()
            status = "ok"
            mask = np.zeros((h, w), dtype=bool)
            if args.model in ("mediapipe", "sam2"):
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                if not result.face_landmarks:
                    status = "no_face"
                else:
                    points = np.array([(v.x * w, v.y * h) for v in result.face_landmarks[0]])
                    outer, inner = points[rings["LIPS_OUTER"]], points[rings["LIPS_INNER"]]
                    if predictor is None:
                        poly = np.zeros((h, w), np.uint8)
                        cv2.fillPoly(poly, [np.rint(outer).astype(np.int32)], 1)
                        cv2.fillPoly(poly, [np.rint(inner).astype(np.int32)], 0)
                        mask = poly.astype(bool)
                    else:
                        try:
                            prompts = make_prompts(outer, inner, (h, w))
                        except ValueError:
                            status = "invalid_prompt"
                        else:
                            with torch.inference_mode():
                                predictor.set_image(rgb)
                                masks, scores, _ = predictor.predict(point_coords=np.array(prompts["points"], np.float32),
                                    point_labels=np.array(prompts["labels"], np.int32), box=np.array(prompts["box"], np.float32), multimask_output=True)
                            mask = masks[int(np.argmax(scores))].astype(bool)
            elif args.model == "segformer":
                import torch.nn.functional as F
                inputs = processor(images=rgb, return_tensors="pt").to("cuda")
                with torch.inference_mode():
                    logits = F.interpolate(net(**inputs).logits, size=(h, w), mode="bilinear", align_corners=False)
                    mask = np.isin(logits.argmax(dim=1)[0].cpu().numpy(), [labels["u_lip"], labels["l_lip"]])
            elif args.model == "bisenet":
                inp = cv2.resize(rgb, (512, 512)).astype(np.float32) / 255
                inp = (inp - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
                logits = net.run(None, {net.get_inputs()[0].name: np.ascontiguousarray(inp.transpose(2, 0, 1)[None])})[0][0]
                classes = cv2.resize(np.argmax(logits, axis=0).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
                mask = np.isin(classes, [12, 13])
            else:
                image = facer.hwc2bchw(torch.from_numpy(rgb)).to("cuda")
                factor = min(1.0, 640 / max(h, w))
                dw, dh = max(1, round(w * factor)), max(1, round(h * factor))
                small = cv2.resize(rgb, (dw, dh), interpolation=cv2.INTER_AREA)
                with torch.inference_mode():
                    faces = detector(facer.hwc2bchw(torch.from_numpy(small)).to("cuda"))
                    count = len(faces["rects"])
                    if count:
                        f = torch.tensor([w / dw, h / dh], device="cuda")
                        faces["rects"] *= f.repeat(2)
                        faces["points"] *= f
                        rect = faces["rects"]
                        index = int(((rect[:, 2] - rect[:, 0]) * (rect[:, 3] - rect[:, 1])).argmax().item())
                        faces = {k: v[index:index + 1] if isinstance(v, torch.Tensor) and v.ndim and v.shape[0] == count else v for k, v in faces.items()}
                        result = parser(image, faces)
                        mask = np.isin(result["seg"]["logits"].argmax(dim=1)[0].cpu().numpy(), labels)
                    else:
                        status = "no_face"
            if args.model != "mediapipe" and args.device == "cuda":
                torch.cuda.synchronize()
            elapsed = 1000 * (time.perf_counter() - start)
            path = mask_dir / f"{frame_i:06d}.png"
            if not cv2.imwrite(str(path), mask.astype(np.uint8) * 255):
                raise IOError(f"Could not save {path}")
            rows.append({"frame": frame_i, "time_seconds": round(frame_i / source_fps, 6),
                         "status": status, "mask_pixels": int(mask.sum()), "elapsed_ms": round(elapsed, 3),
                         "mask": path.name})
            print(f"{args.model}: frame {frame_i}, {status}", flush=True)
            frame_i += 1
            sample_i += 1
    finally:
        cap.release()
        if args.model in ("mediapipe", "sam2"):
            detector.close()
    if not rows:
        raise ValueError("No video frames decoded")
    with (args.output / "frames.csv").open("w", encoding="utf8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    meta.update(source_fps=source_fps, processed_frames=len(rows), width=w, height=h,
                failed=sum(r["status"] != "ok" for r in rows))
    (args.output / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf8")
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()
