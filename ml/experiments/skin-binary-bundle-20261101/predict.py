"""Standalone local inference on task-specific 256px ROIs before preprocessing."""

import argparse
import hashlib
import json
from pathlib import Path

import torch
from PIL import Image, ImageEnhance, ImageFilter
from torch import nn
from torchvision import transforms
from torchvision.models import mobilenet_v3_large

HERE = Path(__file__).resolve().parent
NORMALIZE = transforms.Compose(
    [
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ]
)


def prepare(path):
    with Image.open(path) as image:
        if image.size != (256, 256):
            raise ValueError("Expected a task-specific 256x256 ROI before preprocessing")
        image = image.convert("RGB")
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=75, threshold=0))
        return NORMALIZE(ImageEnhance.Contrast(image).enhance(1.4))


def predict(task, images):
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "skin-binary-three-and-roi-type-v1":
        raise ValueError("Unsupported bundle schema")
    record = manifest["models"][task]
    root = HERE.resolve()
    weight_path = (root / record["file"]).resolve(strict=True)
    if not weight_path.is_relative_to(root):
        raise ValueError("Checkpoint escapes bundle")
    if hashlib.sha256(weight_path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Checkpoint checksum mismatch")
    if task != "skin_type_roi" and len(images) != 1:
        raise ValueError("Each binary task requires one task-specific ROI per call")
    model = mobilenet_v3_large(weights=None)
    outputs = 3 if task == "skin_type_roi" else 1
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, outputs)
    model.load_state_dict(
        torch.load(weight_path, map_location="cpu", weights_only=True)["model_state"], strict=True
    )
    model.eval()
    batch = torch.stack([prepare(path) for path in images])
    with torch.inference_mode():
        logits = model(batch).float()
        if task == "skin_type_roi":
            scores = logits.softmax(1).mean(0).tolist()
            index = max(range(3), key=lambda i: scores[i])
            return dict(
                task=task,
                label=record["classes"][index],
                scores=scores,
                classes=record["classes"],
                roi_count=len(images),
                score_type="mean_uncalibrated_softmax",
            )
        probability = logits.reshape(-1).sigmoid()[0].item()
    index = int(probability >= record["threshold"])
    return dict(
        task=task,
        label=index,
        label_name=record["classes"][index],
        probability_caution=probability,
        threshold=record["threshold"],
        score_type="uncalibrated_sigmoid",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task", required=True, choices=("pore", "pigmentation", "wrinkle", "skin_type_roi")
    )
    parser.add_argument("--image", required=True, action="append")
    args = parser.parse_args()
    print(json.dumps(predict(args.task, args.image), ensure_ascii=False))


if __name__ == "__main__":
    main()
