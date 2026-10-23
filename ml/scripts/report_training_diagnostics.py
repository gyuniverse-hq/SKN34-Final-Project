"""Publish aggregate diagnostics: python -m ml.scripts.report_training_diagnostics."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch

from skin_analysis.smartphone.common import file_hash, load_config, load_manifest, write_json
from skin_analysis.smartphone.diagnostics import DEFAULT_CONFIG, root_for
from skin_analysis.smartphone.focal_compare import verified_metrics


def main():
    config = load_config(DEFAULT_CONFIG)
    root = root_for(config)
    tiny = json.loads((root / "tiny-ce/result.json").read_text(encoding="utf-8"))
    gaps = json.loads((root / "checkpoint-gaps.json").read_text(encoding="utf-8"))
    history = json.loads(
        (Path(config["train"]["output"]) / "pore/history.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (Path(config["train"]["output"]) / "pore/summary.json").read_text(encoding="utf-8")
    )
    before = json.loads((root / "preservation-before.json").read_text(encoding="utf-8"))
    assert before == {path: file_hash(path) for path in before}, "Preserved assets changed"
    old_root = Path(config["train"]["output"]).parents[1] / "nia-smartphone-ce-batch16-seed-42/pore"
    previous = json.loads((old_root / "history.json").read_text(encoding="utf-8"))
    replay_keys = (
        "epoch",
        "stage",
        "train_loss",
        "valid_loss",
        "valid_accuracy",
        "valid_macro_f1",
        "valid_within_one",
        "selected",
        "amp_overflow_retries",
    )
    assert len(previous) == len(history)
    assert all(
        all(a[key] == b[key] for key in replay_keys) for a, b in zip(previous, history, strict=True)
    ), "Diagnostic evaluation perturbed training history"
    old_state = torch.load(old_root / "inference.bin", map_location="cpu", weights_only=True)[
        "model_state"
    ]
    new_state = torch.load(
        Path(config["train"]["output"]) / "pore/inference.bin",
        map_location="cpu",
        weights_only=True,
    )["model_state"]
    assert old_state.keys() == new_state.keys()
    assert all(torch.equal(old_state[k], new_state[k]) for k in old_state)
    del old_state, new_state
    manifest = load_manifest(config)
    labels = [
        r["truth"] for r in manifest["records"] if r["task"] == "pore" and r["split"] == "train"
    ]
    majority = max(range(6), key=labels.count)
    majority_metrics = {}
    grade_subjects = {}
    for split in ("train", "valid"):
        truth = [
            r["truth"] for r in manifest["records"] if r["task"] == "pore" and r["split"] == split
        ]
        majority_metrics[split] = verified_metrics(truth, [majority] * len(truth), 6)
        grade_subjects[split] = [
            len(
                {
                    r["subject"]
                    for r in manifest["records"]
                    if r["task"] == "pore" and r["split"] == split and r["truth"] == grade
                }
            )
            for grade in range(6)
        ]
    public = dict(
        schema="nia-training-diagnostics-report-v1",
        tiny=tiny,
        checkpoint_gaps=gaps,
        training_history=history,
        selected_summary=summary,
        majority_baseline=dict(grade=majority, splits=majority_metrics),
        grade_subject_support=grade_subjects,
        preservation=dict(files=len(before), passed=True),
        replay_verification=dict(all_epochs_identical=True, selected_model_tensors_identical=True),
        test_set_evaluated=False,
    )
    reports = Path(__file__).resolve().parents[2] / "reports/skin-analysis"
    write_json(reports / "training-diagnostics.metrics.json", public)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    small = tiny["history"]
    axes[0, 0].plot(
        [r["optimizer_steps"] for r in small],
        [r["metrics"]["accuracy"] for r in small],
        "o-",
        label="Train accuracy",
    )
    axes[0, 0].plot(
        [r["optimizer_steps"] for r in small],
        [r["metrics"]["macro_f1"] for r in small],
        "s--",
        label="Train macro F1",
    )
    axes[0, 0].set(
        title="48 training ROIs / 48 people: memorization only",
        xlabel="Optimizer updates",
        ylabel="Score",
        ylim=(0, 1.05),
    )
    for ax, train_key, valid_key, title, ylabel in (
        (axes[0, 1], "train_eval_accuracy", "valid_accuracy", "Full data: accuracy", "Score"),
        (axes[1, 0], "train_eval_macro_f1", "valid_macro_f1", "Full data: macro F1", "Score"),
        (axes[1, 1], "train_eval_loss", "valid_loss", "Full data: matched unweighted CE", "Loss"),
    ):
        epochs = [r["epoch"] for r in history]
        ax.plot(epochs, [r[train_key] for r in history], "o-", label="Train (no augmentation)")
        ax.plot(epochs, [r[valid_key] for r in history], "s-", label="Validation")
        ax.axvline(summary["best_epoch"], color="grey", linestyle=":", label="Selected epoch")
        ax.set(title=title, xlabel="Epoch", ylabel=ylabel)
        if ylabel == "Score":
            ax.set_ylim(0, 1.05)
    for ax in axes.flat:
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
    fig.suptitle("Pore diagnostics: same eval mode; final test set unused")
    figure = reports / "figures/pore-training-diagnostics.png"
    figure.parent.mkdir(exist_ok=True)
    fig.savefig(figure, dpi=160)
    plt.close(fig)
    document = reports / "training-diagnostics.md"
    prefix = document.read_text(encoding="utf-8").split("\n## 실제 진단 결과")[0]
    lines = ["", "## 실제 진단 결과", "", "### 소량 암기 검사", ""]
    last = tiny["history"][-1]
    lines += [
        f"통과: **{tiny['passed']}**. {last['epoch']} epoch / "
        f"{last['optimizer_steps']} 업데이트에서 "
        f"Accuracy {last['metrics']['accuracy']:.2%}, macro-F1 {last['metrics']['macro_f1']:.2%}, "
        f"unweighted CE {last['unweighted_ce']:.6f}.",
        "",
        "### 선택 가중치의 학습/검증 차이",
        "",
        "| 모델 | epoch | 학습 Accuracy | 검증 Accuracy | 학습 macro F1 | "
        "검증 macro F1 | F1 차이(%p) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in gaps["results"].items():
        train = result["splits"]["train"]["metrics"]
        valid = result["splits"]["valid"]["metrics"]
        lines.append(
            f"| {name} | {result['epoch']} | {train['accuracy']:.2%} | {valid['accuracy']:.2%} | "
            f"{train['macro_f1']:.2%} | {valid['macro_f1']:.2%} | "
            f"{(train['macro_f1'] - valid['macro_f1']) * 100:.2f} |"
        )
    lines += [
        "",
        "### 학습 곡선",
        "",
        "![모공 학습 진단 곡선](figures/pore-training-diagnostics.png)",
        "",
        f"선택 epoch {summary['best_epoch']}, 실제 실행 {summary['epochs_run']} epoch.",
        "",
        "개별 예측과 인물 식별자는 공개 보고서에 포함하지 않습니다. "
        "전체 혼동행렬·등급별 집계는 [집계 JSON](training-diagnostics.metrics.json)에 있습니다.",
        "",
    ]
    document.write_text(prefix + "\n".join(lines), encoding="utf-8")
    print("Published aggregate report and learning-curve figure; preserved files verified.")


if __name__ == "__main__":
    main()
