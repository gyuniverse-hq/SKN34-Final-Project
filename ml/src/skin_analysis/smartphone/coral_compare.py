"""Compare preserved CE / CB Focal / CORAL models on validation only."""

import argparse
import json
from pathlib import Path

import torch
from torchvision.models import resnet50

from ..config import PROJECT_ROOT
from ..runtime import select_cuda
from .common import TASKS, file_hash, load_config, load_manifest, write_json
from .coral import ARCHITECTURE, load_coral_checkpoint
from .data import GradeDataset
from .focal_compare import qualifies, require_matched_conditions, verified_metrics
from .train import make_loader, predict, verify_crops

DEFAULT_CONFIG = PROJECT_ROOT / "configs/nia_smartphone_coral.toml"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/coral-experiment.md"


def compare(config, task):
    manifest = load_manifest(config)
    verify_crops(manifest)
    output = Path(config["train"]["output"])
    destination = output / f"{task}-comparison.json"
    if destination.exists():
        raise FileExistsError("Validation comparison exists; publish the saved result")
    baseline_root = PROJECT_ROOT / config["comparison"]["baseline"] / task
    baseline = torch.load(baseline_root / "best.pt", map_location="cpu", weights_only=True)
    require_matched_conditions(config, manifest, baseline)
    candidate = torch.load(output / task / "best.pt", map_location="cpu", weights_only=True)
    if (
        baseline["task"] != task
        or candidate["task"] != task
        or candidate["architecture"] != ARCHITECTURE
        or candidate["train_config"] != config["train"]
        or candidate["manifest_fingerprint"] != manifest["fingerprint"]
        or candidate["initialization"] != baseline["initialization"]
        or candidate["environment"]["packages"] != baseline["environment"]["packages"]
    ):
        raise ValueError("CORAL conditions or provenance mismatch")
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    data = GradeDataset(manifest, task, "valid")
    loader = make_loader(data, config["train"])
    paths = {"ce": baseline_root / "inference.bin"}
    focal_path = PROJECT_ROOT / config["comparison"]["focal"] / task / "inference.bin"
    if focal_path.exists():
        paths["cb_focal"] = focal_path
    paths["coral"] = output / task / "inference.bin"
    results = {}
    for variant, path in paths.items():
        ordinal = variant == "coral"
        summary = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
        if file_hash(path) != summary["sha256"]:
            raise ValueError("Inference file differs from completed training summary")
        if ordinal:
            model, checkpoint = load_coral_checkpoint(path, summary["sha256"])
        else:
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            model = resnet50(weights=None, num_classes=TASKS[task]["classes"])
            model.load_state_dict(checkpoint["model_state"], strict=True)
        if (
            checkpoint["task"] != task
            or checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
            or checkpoint["initialization"] != baseline["initialization"]
            or checkpoint["environment"]["packages"] != baseline["environment"]["packages"]
            or checkpoint["preprocessing"] != manifest["preprocessing"]
        ):
            raise ValueError("Inference checkpoint provenance mismatch")
        model = model.to(device).eval()
        truth, predicted, probabilities, loss = predict(model, loader, device, ordinal=ordinal)
        results[variant] = dict(
            sha256=file_hash(path),
            epoch=checkpoint["epoch"] + 1,
            architecture=checkpoint["architecture"],
            unweighted_validation_loss=loss,
            loss_type="sum_threshold_bce" if ordinal else "multiclass_ce",
            metrics=verified_metrics(truth, predicted, TASKS[task]["classes"]),
        )
        write_json(
            output / f"{task}-validation-{variant}-predictions.json",
            dict(
                ids=[r["id"] for r in data.records],
                truth=truth,
                predicted=predicted,
                probability_semantics="P(y>k)" if ordinal else "P(y=k)",
                probabilities=probabilities,
            ),
        )
        del model, checkpoint
        torch.cuda.empty_cache()
    result = dict(
        schema="nia-coral-validation-v1",
        task=task,
        subjects=len({r["subject"] for r in data.records}),
        data_fingerprint=manifest["fingerprint"],
        phase="validation_only",
        test_set_evaluated=False,
        condition_check="passed",
        selection_policy=config["comparison"]["policy"],
        qualifies_for_expansion=qualifies(results["ce"]["metrics"], results["coral"]["metrics"]),
        results=results,
    )
    write_json(destination, result)
    print(json.dumps(result), flush=True)


def publish(config):
    output = Path(config["train"]["output"])
    tasks = {
        task: json.loads(path.read_text(encoding="utf-8"))
        for task in TASKS
        if (path := output / f"{task}-comparison.json").exists()
    }
    if "pore" not in tasks:
        raise ValueError("Complete pore comparison first")
    text = REPORT.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    lines = ["", "## 실제 비교 결과", ""]
    for task, result in tasks.items():
        lines += [
            f"### {task}",
            "",
            f"검증 {result['subjects']}명, 최종 평가셋 사용 없음. "
            f"확대 기준 충족: **{result['qualifies_for_expansion']}**.",
            "",
            "| 모델 | epoch | Accuracy | macro P | macro R | macro F1 | MAE | "
            "±1등급 | 고등급 Recall |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for name, row in result["results"].items():
            m = row["metrics"]
            lines.append(
                f"| {name} | {row['epoch']} | {m['accuracy']:.2%} | "
                f"{m['macro_precision']:.2%} | {m['macro_recall']:.2%} | {m['macro_f1']:.2%} | "
                f"{m['mae']:.4f} | {m['within_one']:.2%} | {m['high_grade_pooled_recall']:.2%} |"
            )
        lines += [
            "",
            "| 모델 | 등급 | 실제 ROI | 예측 ROI | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, row in result["results"].items():
            for g in row["metrics"]["per_grade"]:
                lines.append(
                    f"| {name} | {g['grade']} | {g['support']} | {g['predicted']} | "
                    f"{g['precision']:.2%} | {g['recall']:.2%} | {g['f1']:.2%} |"
                )
        lines += ["", "가중치 SHA-256:", ""]
        for name, row in result["results"].items():
            lines.append(f"- {name}: `{row['sha256']}`")
        lines.append("")
    REPORT.write_text(text + "\n".join(lines), encoding="utf-8")
    write_json(REPORT.with_suffix(".metrics.json"), dict(schema="nia-coral-report-v1", tasks=tasks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", choices=TASKS, default="pore")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.publish:
        publish(config)
    else:
        compare(config, args.task)


if __name__ == "__main__":
    main()
