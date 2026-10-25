"""Evaluate pore cap-ablation checkpoints on the existing validation split only."""

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    from server.nia.metrics import classification

    from skin_analysis.runtime import select_cuda
    from skin_analysis.smartphone.common import load_config, load_manifest
    from skin_analysis.smartphone.data import GradeDataset
    from skin_analysis.smartphone.train import GradeModel, make_loader, predict

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    manifest = load_manifest(config)
    settings = config["train"]
    device = select_cuda(settings["device_uuid"])
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = GradeModel(6, pretrained=False, backbone="resnet50").to(device)
    model.network.load_state_dict(checkpoint["model_state"], strict=True)
    dataset = GradeDataset(manifest, "pore", "valid")
    loader = make_loader(dataset, settings)
    truth, predicted, _, _ = predict(model, loader, device)
    metrics = classification(truth, predicted, 6)
    high_support = sum(actual >= 4 for actual in truth)
    high_predicted = sum(prediction >= 4 for prediction in predicted)
    high_detected = sum(
        actual >= 4 and prediction >= 4 for actual, prediction in zip(truth, predicted, strict=True)
    )
    metrics["high_grade_exact_recall"] = (
        sum(
            actual == prediction and actual >= 4
            for actual, prediction in zip(truth, predicted, strict=True)
        )
        / high_support
    )
    metrics["high_grade_detection_recall"] = high_detected / high_support
    metrics["high_grade_detection_precision"] = (
        high_detected / high_predicted if high_predicted else 0.0
    )
    metrics["subjects"] = len({r["subject"] for r in dataset.records})
    metrics["grades_subject_support"] = [
        len({r["subject"] for r in dataset.records if dataset.target(r) == grade})
        for grade in range(6)
    ]
    output = args.checkpoint.parent / "evaluation.json"
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evaluation": str(output), "macro_f1": metrics["macro_f1"]}), flush=True)


if __name__ == "__main__":
    main()
