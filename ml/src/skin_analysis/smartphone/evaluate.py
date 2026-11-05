"""Evaluate a fixed phone-only holdout after validation-based model selection."""

import argparse
import copy
import json
from pathlib import Path

import torch
from server.nia.metrics import classification
from server.nia.recommendation import export_bundle
from torchvision.models import resnet50

from ..runtime import select_cuda
from .common import (
    DEFAULT_CONFIG,
    TASKS,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from .data import GradeDataset
from .train import make_loader, predict, verify_crops


def metrics_for(records, truth, predicted, classes):
    return {
        "overall": classification(truth, predicted, classes),
        "areas": {
            area: classification(
                [truth[i] for i in indices], [predicted[i] for i in indices], classes
            )
            for area in sorted({r["area"] for r in records})
            if (indices := [i for i, record in enumerate(records) if record["area"] == area])
        },
    }


def evaluate(config, legacy_config, device):
    manifest = load_manifest(config)
    verify_crops(manifest)
    output = Path(config["train"]["output"])
    report_path = output / "evaluation.json"
    if report_path.exists():
        raise FileExistsError("Final evaluation already exists; do not repeatedly tune to holdout")
    legacy = json.loads(Path(legacy_config).read_text(encoding="utf-8"))
    results = {}
    for task, spec in TASKS.items():
        data = GradeDataset(manifest, task, "test")
        loader = make_loader(data, config["train"])
        selected_path = output / task / "inference.bin"
        selected = torch.load(selected_path, map_location="cpu", weights_only=True)
        if selected["manifest_fingerprint"] != manifest["fingerprint"]:
            raise ValueError("Trained model and evaluation data have different provenance")
        old = [m for m in legacy["models"] if m["task"] == f"class/{task}"]
        if len(old) != 1 or file_hash(old[0]["checkpoint"]) != old[0]["sha256"]:
            raise ValueError("Original comparison checkpoint is missing or changed")
        runs = {}
        for name, path in (("smartphone", selected_path), ("legacy_nia", old[0]["checkpoint"])):
            model = resnet50(weights=None, num_classes=spec["classes"])
            state = torch.load(path, map_location="cpu", weights_only=True)["model_state"]
            model.load_state_dict(state, strict=True)
            model = model.to(device).eval()
            truth, predicted, probabilities, loss = predict(model, loader, device)
            runs[name] = dict(
                sha256=file_hash(path),
                unweighted_ce=loss,
                **metrics_for(data.records, truth, predicted, spec["classes"]),
            )
            # Individual predictions stay under ignored ml/runs, never in public reports.
            write_json(
                output / task / f"test-{name}.json",
                dict(
                    ids=[r["id"] for r in data.records],
                    truth=truth,
                    predicted=predicted,
                    probabilities=probabilities,
                ),
            )
            del model, state
            torch.cuda.empty_cache()
        training = [
            r["truth"] for r in manifest["records"] if r["task"] == task and r["split"] == "train"
        ]
        majority = max(range(spec["classes"]), key=training.count)
        runs["train_majority"] = metrics_for(
            data.records, truth, [majority] * len(truth), spec["classes"]
        )
        summary = json.loads((output / task / "summary.json").read_text(encoding="utf-8"))
        results[task] = dict(**runs, **summary)
        print(
            json.dumps(
                {
                    "task": task,
                    "smartphone": runs["smartphone"]["overall"],
                    "legacy_nia": runs["legacy_nia"]["overall"],
                }
            ),
            flush=True,
        )
        del loader
    report = dict(
        schema="nia-smartphone-evaluation-v1",
        data_fingerprint=manifest["fingerprint"],
        data=manifest["summary"],
        exclusions=manifest["excluded"],
        source_photo_count=manifest["source_photo_count"],
        tasks=results,
        training_settings=config["train"],
        split_settings=config["data"],
        caveats=[
            "New subject-disjoint research split; not the published paper split.",
            "Original NIA model may have seen these subjects in DSLR training.",
            "Annotated ROIs; automatic selfie ROI detection is not validated.",
            "NIA smartphone images have controlled capture conditions.",
            "Acne is unchanged and remains synthetic-data-trained.",
        ],
    )
    write_json(report_path, report)
    return report


def activate(config, legacy_config):
    output = Path(config["train"]["output"])
    if not (output / "evaluation.json").exists():
        raise ValueError("Complete final evaluation before activating experimental weights")
    path = Path(legacy_config)
    original = json.loads(path.read_text(encoding="utf-8"))
    backup = output / "config.before-smartphone.json"
    if backup.exists():
        raise FileExistsError("Activation backup already exists")
    write_json(backup, original)
    updated = copy.deepcopy(original)
    manifest = load_manifest(config)
    for model in updated["models"]:
        task = model["task"].removeprefix("class/")
        if model["task"] not in {f"class/{task}" for task in TASKS}:
            continue
        trained = output / task / "inference.bin"
        model.update(
            id=f"nia-smartphone-class-{task}",
            checkpoint=str(trained),
            sha256=file_hash(trained),
            training_device="smartphone",
            training_resolution_confirmed=True,
            data_fingerprint=manifest["fingerprint"],
            source="New smartphone-only ResNet-50 training from ImageNet V2; "
            "no original NIA weights. Subject-disjoint research split seed 42.",
            label_evidence="Original AI-Hub smartphone visual-grade annotations; "
            "official square-JPEG 256px crop and ImageNet normalization.",
        )
        model.pop("original_checkpoint", None)
        model.pop("original_sha256", None)
    candidate = output / "config.smartphone.json"
    write_json(candidate, updated)
    # A new versioned bundle preserves both the original bundle and original NIA files.
    bundle = export_bundle(candidate, output / "recommendation-bundle")
    temporary = path.with_suffix(".tmp")
    write_json(temporary, updated)
    temporary.replace(path)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--legacy-config", type=Path, default=Path("server/nia/config.local.json"))
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.activate:
        print(activate(config, args.legacy_config))
    else:
        device = select_cuda(config["train"]["device_uuid"])
        torch.set_num_threads(4)
        evaluate(config, args.legacy_config, device)


if __name__ == "__main__":
    main()
