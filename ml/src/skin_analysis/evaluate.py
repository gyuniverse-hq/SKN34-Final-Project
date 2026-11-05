"""Choose thresholds on validation only, then evaluate the held-out test set."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import torch

from .audit import require_approved
from .config import DEFAULT_CONFIG, class_key, load_config, write_json
from .dataset import SkinDataset, make_loader
from .metrics import classification_metrics, group_bootstrap, select_thresholds
from .runtime import load_checkpoint, model_from_checkpoint, save_checkpoint, select_cuda
from .train import predict_loader


def subgroup_metrics(targets, scores, records, classes, thresholds) -> dict:
    normal = next((i for i, name in enumerate(classes) if class_key(name) == "normal skin"), None)
    disease = targets.sum(axis=1) - (targets[:, normal] if normal is not None else 0)
    masks = {
        "single_condition": disease == 1,
        "compound": disease >= 2,
        "normal_only": ((targets[:, normal] == 1) & (disease == 0))
        if normal is not None
        else np.zeros(len(targets), dtype=bool),
    }
    for image_type in ("full_face", "partial_face", "skin_closeup", "non_face", "unknown"):
        masks[image_type] = np.array([r["image_type"] == image_type for r in records])
    result = {}
    for name, mask in masks.items():
        indices = np.flatnonzero(mask)
        result[name] = {
            "images": len(indices),
            "groups": len({records[i]["group_id"] for i in indices}),
            "metrics": classification_metrics(targets[mask], scores[mask], classes, thresholds)
            if len(indices)
            else None,
            "limitation": "Insufficient subgroup support; separate validation required"
            if len(indices) < 30
            else None,
        }
    return result


def save_pr_curves(metrics: dict, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    columns = 3
    rows = (len(metrics["classes"]) + columns - 1) // columns
    figure, axes = plt.subplots(rows, columns, figsize=(12, 3.5 * rows), squeeze=False)
    for index, item in enumerate(metrics["classes"]):
        axis = axes.flat[index]
        curve = item["pr_curve"]
        if curve:
            axis.step(curve["recall"], curve["precision"], where="post")
        axis.set(title=item["class"], xlabel="Recall", ylabel="Precision", xlim=(0, 1), ylim=(0, 1))
    for axis in list(axes.flat)[len(metrics["classes"]) :]:
        axis.set_visible(False)
    figure.tight_layout()
    figure.savefig(output / "test-pr-curves.png", dpi=150)
    plt.close(figure)


def evaluate(config: dict, checkpoint_path: Path, output: Path, cuda: bool = False) -> dict:
    _, manifest = require_approved(config)
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint.get("kind") != "training":
        raise ValueError("Calibration requires the selected training best.pt")
    last = checkpoint["history"][-1]
    if (
        last["valid_macro_ap"] != checkpoint["best_ap"]
        or last["valid_bce"] != checkpoint["best_loss"]
    ):
        raise ValueError("Checkpoint is not the validation-selected best model")
    if (
        checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["classes"] != manifest["classes"]
    ):
        raise ValueError(
            "Checkpoint dataset fingerprint/class order differs from the current audit"
        )
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Evaluation output must be empty; test results cannot be overwritten")
    device = select_cuda(config["train"]["device_uuid"]) if cuda else torch.device("cpu")
    model = model_from_checkpoint(checkpoint, device)
    valid_data, test_data = SkinDataset(manifest, "valid"), SkinDataset(manifest, "test")
    batch, workers = checkpoint["micro_batch"], config["train"]["num_workers"]
    valid_loader = make_loader(valid_data, batch, workers, config["evaluation"]["seed"])
    valid_y, valid_scores, _ = predict_loader(model, valid_loader, device)
    thresholds = select_thresholds(valid_y, valid_scores)
    train_y = np.array([r["labels"] for r in manifest["records"] if r["split"] == "train"])
    prevalence = train_y.mean(axis=0)
    valid_baseline = np.broadcast_to(prevalence, valid_y.shape)
    baseline_thresholds = select_thresholds(valid_y, valid_baseline)
    # All threshold/config choices above are finalized before this test prediction.
    test_loader = make_loader(test_data, batch, workers, config["evaluation"]["seed"])
    test_y, test_scores, _ = predict_loader(model, test_loader, device)
    baseline = np.broadcast_to(prevalence, test_y.shape)
    selected = classification_metrics(test_y, test_scores, manifest["classes"], thresholds)
    reference = classification_metrics(test_y, baseline, manifest["classes"], baseline_thresholds)
    bootstrap = group_bootstrap(
        test_y,
        test_scores,
        baseline,
        [r["group_id"] for r in test_data.records],
        thresholds,
        baseline_thresholds,
        config["evaluation"]["bootstrap_iterations"],
        config["evaluation"]["seed"],
    )
    improvement = bootstrap["macro_f1_difference_ci95"]
    success = (
        selected["macro_f1"] is not None
        and reference["macro_f1"] is not None
        and selected["macro_f1"] > reference["macro_f1"]
        and selected["micro_f1"] > reference["micro_f1"]
        and all(row["recall"] is not None and row["recall"] > 0 for row in selected["classes"])
        and improvement is not None
        and improvement[0] > 0
    )
    predictions = test_scores >= np.array(thresholds)
    normal = next(
        (i for i, c in enumerate(manifest["classes"]) if class_key(c) == "normal skin"), None
    )
    normal_conflicts = (
        int(np.sum(predictions[:, normal] & (predictions.sum(axis=1) > 1)))
        if normal is not None
        else 0
    )
    report = {
        "schema_version": 1,
        "classes": manifest["classes"],
        "manifest_fingerprint": manifest["fingerprint"],
        "score_type": "sigmoid_uncalibrated",
        "threshold_source": "validation_only",
        "thresholds": thresholds,
        "validation": classification_metrics(
            valid_y, valid_scores, manifest["classes"], thresholds
        ),
        "test_at_05": classification_metrics(test_y, test_scores, manifest["classes"]),
        "test_selected": selected,
        "baseline": reference,
        "baseline_train_prevalence": prevalence.tolist(),
        "baseline_thresholds": baseline_thresholds,
        "bootstrap": bootstrap,
        "research_success": bool(success),
        "predicted_normal_and_condition": normal_conflicts,
        "subgroups": subgroup_metrics(
            test_y, test_scores, test_data.records, manifest["classes"], thresholds
        ),
        "limitations": [
            "Sigmoid scores are uncalibrated and do not measure severity",
            "Global/skin-tone and unverified-person generalization are not established",
            "Validation metrics also reflect checkpoint/threshold selection",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    save_pr_curves(selected, output)
    model_hash = hashlib.sha256()
    with checkpoint_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            model_hash.update(chunk)
    bundle = {
        key: checkpoint[key]
        for key in (
            "schema_version",
            "architecture",
            "weights",
            "classes",
            "model_state",
            "preprocessing",
            "score_type",
            "manifest_fingerprint",
            "evidence",
            "environment",
            "train_config",
            "epoch",
        )
    }
    bundle.update(
        {
            "kind": "inference",
            "model_id": model_hash.hexdigest(),
            "thresholds": thresholds,
            "threshold_source": "validation_only",
            "research_success": bool(success),
        }
    )
    save_checkpoint(output / "inference.pt", bundle)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cuda", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    run = Path(config["train"]["output"])
    result = evaluate(
        config, args.checkpoint or run / "best.pt", args.output or run / "evaluation", args.cuda
    )
    print(
        f"Research success: {result['research_success']}; test macro F1: "
        f"{result['test_selected']['macro_f1']}"
    )


if __name__ == "__main__":
    main()
