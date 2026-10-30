"""Validation-only comparison against the preserved smartphone CE checkpoint."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from server.nia.metrics import classification
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from torchvision.models import resnet50

from ..config import PROJECT_ROOT
from ..runtime import select_cuda
from .common import TASKS, file_hash, load_config, load_manifest, write_json
from .data import GradeDataset
from .train import make_loader, predict, verify_crops

DEFAULT_FOCAL_CONFIG = PROJECT_ROOT / "configs/nia_smartphone_cb_focal.toml"
LOSS_KEYS = {
    "loss",
    "cb_beta",
    "focal_gamma",
    "weight_exponent",
    "class_weight_cap",
}


def require_matched_conditions(config, manifest, baseline):
    excluded = LOSS_KEYS | {"output"}
    settings = {k: v for k, v in config["train"].items() if k not in excluded}
    previous = {k: v for k, v in baseline["train_config"].items() if k not in excluded}
    if (
        settings != previous
        or baseline["manifest_fingerprint"] != manifest["fingerprint"]
        or baseline["initialization"].get("nia_weights_used") is not False
        or baseline["preprocessing"] != manifest["preprocessing"]
    ):
        raise ValueError("Baseline and candidate must share all non-loss training conditions")


def high_grade_recall(metrics):
    grades = metrics["per_grade"][-2:]
    support = sum(g["support"] for g in grades)
    if not support:
        raise ValueError("Validation requires examples from the highest grades")
    return sum(metrics["confusion"][g["grade"]][g["grade"]] for g in grades) / support


def qualifies(baseline, candidate):
    return (
        candidate["macro_f1"] > baseline["macro_f1"] + 1e-12
        and candidate["accuracy"] + 1e-12 >= baseline["accuracy"]
        and high_grade_recall(candidate) > high_grade_recall(baseline) + 1e-12
    )


def verified_metrics(truth, predicted, classes):
    metrics = classification(truth, predicted, classes)
    labels = list(range(classes))
    assert np.isclose(metrics["accuracy"], accuracy_score(truth, predicted), rtol=1e-12, atol=1e-12)
    assert metrics["confusion"] == confusion_matrix(truth, predicted, labels=labels).tolist()
    for average in ("macro", "weighted"):
        precision, recall, f1, _ = precision_recall_fscore_support(
            truth, predicted, labels=labels, average=average, zero_division=0
        )
        for suffix, value in (("precision", precision), ("recall", recall), ("f1", f1)):
            assert np.isclose(metrics[f"{average}_{suffix}"], value, rtol=1e-12, atol=1e-12)
    metrics["high_grade_pooled_recall"] = high_grade_recall(metrics)
    return metrics


def comparison_paths(config, task):
    output = Path(config["train"]["output"])
    baseline = (PROJECT_ROOT / config["comparison"]["baseline"]).resolve()
    return output, baseline / task


def evaluate_validation(config, task, baseline_only=False):
    manifest = load_manifest(config)
    verify_crops(manifest)
    output, baseline_root = comparison_paths(config, task)
    output.mkdir(parents=True, exist_ok=True)
    baseline = torch.load(baseline_root / "best.pt", map_location="cpu", weights_only=True)
    if baseline["task"] != task:
        raise ValueError("Baseline task mismatch")
    require_matched_conditions(config, manifest, baseline)
    destination = output / f"{task}-{'baseline-validation' if baseline_only else 'comparison'}.json"
    if destination.exists():
        raise FileExistsError("Comparison already recorded; publish the saved result")
    if not baseline_only:
        candidate = torch.load(output / task / "best.pt", map_location="cpu", weights_only=True)
        if (
            candidate["initialization"] != baseline["initialization"]
            or candidate["manifest_fingerprint"] != baseline["manifest_fingerprint"]
            or candidate["environment"]["packages"] != baseline["environment"]["packages"]
            or candidate["task"] != task
            or candidate["train_config"] != config["train"]
        ):
            raise ValueError("Initialization, data or package versions differ")
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    data = GradeDataset(manifest, task, "valid")
    loader = make_loader(data, config["train"])
    paths = {"baseline": baseline_root / "inference.bin"}
    if not baseline_only:
        paths["candidate"] = output / task / "inference.bin"
    results = {}
    for variant, path in paths.items():
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        model = resnet50(weights=None, num_classes=TASKS[task]["classes"])
        model.load_state_dict(checkpoint["model_state"], strict=True)
        model = model.to(device).eval()
        truth, predicted, probabilities, ce = predict(model, loader, device)
        results[variant] = dict(
            sha256=file_hash(path),
            epoch=checkpoint["epoch"] + 1,
            unweighted_ce=ce,
            metrics=verified_metrics(truth, predicted, TASKS[task]["classes"]),
        )
        write_json(
            output / f"{task}-validation-{variant}-predictions.json",
            dict(
                ids=[r["id"] for r in data.records],
                truth=truth,
                predicted=predicted,
                probabilities=probabilities,
            ),
        )
        del model, checkpoint
        torch.cuda.empty_cache()
    qualified = (
        qualifies(results["baseline"]["metrics"], results["candidate"]["metrics"])
        if not baseline_only
        else None
    )
    result = dict(
        schema="nia-cb-focal-validation-v1",
        task=task,
        phase="validation_only",
        data_fingerprint=manifest["fingerprint"],
        subjects=len({r["subject"] for r in data.records}),
        test_set_evaluated=False,
        condition_check="passed",
        selection_policy=config["comparison"]["policy"],
        qualifies_for_expansion=qualified,
        loss_settings={k: config["train"][k] for k in sorted(LOSS_KEYS)},
        results=results,
    )
    write_json(destination, result)
    print(json.dumps(result), flush=True)


def publish(config, task):
    output, _ = comparison_paths(config, task)
    result = json.loads((output / f"{task}-comparison.json").read_text(encoding="utf-8"))
    document = Path("reports/skin-analysis/cb-focal-experiment.md")
    text = document.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    lines = [
        "",
        "## 실제 비교 결과",
        "",
        f"항목 `{task}`, 검증 인물 {result['subjects']}명. "
        "최종 평가셋은 이번 비교에 사용하지 않았습니다.",
        "",
        "| 모델 | 선택 epoch | Accuracy | macro Precision | macro Recall | "
        "macro-F1 | ±1등급 | 고등급 Recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant, row in result["results"].items():
        metrics = row["metrics"]
        values = [
            f"{metrics[k] * 100:.2f}%"
            for k in (
                "accuracy",
                "macro_precision",
                "macro_recall",
                "macro_f1",
                "within_one",
                "high_grade_pooled_recall",
            )
        ]
        lines.append(f"| {variant} | {row['epoch']} | " + " | ".join(values) + " |")
    lines += [
        "",
        "### 등급별 비교",
        "",
        "| 모델 | 등급 | 실제 ROI | 예측 ROI | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for variant, row in result["results"].items():
        for grade in row["metrics"]["per_grade"]:
            lines.append(
                f"| {variant} | {grade['grade']} | {grade['support']} | {grade['predicted']} | "
                f"{grade['precision'] * 100:.2f}% | {grade['recall'] * 100:.2f}% | "
                f"{grade['f1'] * 100:.2f}% |"
            )
    lines += ["", "### 가중치", ""]
    for variant, row in result["results"].items():
        lines.append(f"- {variant}: `{row['sha256']}`")
    lines += [
        "",
        f"사전에 정한 확대 조건 충족: **{result['qualifies_for_expansion']}**.",
        "이 결과는 검증셋 비교이며 독립 최종 성능 추정이 아닙니다.",
        "",
    ]
    document.write_text(text + "\n".join(lines), encoding="utf-8")
    write_json(document.with_suffix(".metrics.json"), result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_FOCAL_CONFIG)
    parser.add_argument("--task", choices=TASKS, default="pore")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.publish:
        publish(config, args.task)
    else:
        evaluate_validation(config, args.task, args.baseline_only)


if __name__ == "__main__":
    main()
