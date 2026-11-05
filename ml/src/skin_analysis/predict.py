"""Standalone single-image inference; no HTTP or application integration."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

from .config import DEFAULT_CONFIG, load_config
from .runtime import load_checkpoint, model_from_checkpoint, select_cuda
from .transforms import make_transform


@torch.inference_mode()
def predict(checkpoint_path: Path, image_path: Path, device: torch.device | None = None) -> dict:
    checkpoint = load_checkpoint(checkpoint_path)
    thresholds = np.asarray(checkpoint.get("thresholds"), dtype=float)
    if checkpoint.get("kind") != "inference" or thresholds.shape != (len(checkpoint["classes"]),):
        raise ValueError("Use an inference.pt bundle with validation-selected thresholds")
    if not np.isfinite(thresholds).all() or (thresholds < 0).any() or (thresholds > 1).any():
        raise ValueError("Invalid checkpoint thresholds")
    device = device or torch.device("cpu")
    model = model_from_checkpoint(checkpoint, device)
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        inputs = make_transform(recipe=checkpoint["preprocessing"])(image).unsqueeze(0).to(device)
    scores = model(inputs).float().sigmoid().squeeze(0).cpu().numpy()
    if not np.isfinite(scores).all():
        raise RuntimeError("Non-finite inference scores")
    return {
        "model_id": checkpoint["model_id"],
        "classes": checkpoint["classes"],
        "score_type": "sigmoid_uncalibrated",
        "scores": scores.tolist(),
        "thresholds": thresholds.tolist(),
        "positive": (scores >= thresholds).tolist(),
        "research_success": checkpoint["research_success"],
        "interpretation": "Uncalibrated classification scores; not severity or actual probability",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--cuda", action="store_true")
    args = parser.parse_args()
    device = select_cuda(load_config(args.config)["train"]["device_uuid"]) if args.cuda else None
    print(
        json.dumps(
            predict(args.checkpoint, args.image, device), ensure_ascii=False, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()
