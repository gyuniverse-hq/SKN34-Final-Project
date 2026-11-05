"""Generate per-task experiment tables and integer-epoch learning curves."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402


def write_report(output):
    output = Path(output)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    history = json.loads((output / "history.json").read_text(encoding="utf-8"))
    contract = summary["contract"]
    test = summary["candidate_test"]
    report = output / "report"
    report.mkdir(exist_ok=True)
    epochs = [row["epoch"] for row in history]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    panels = [
        ("macro_f1", "Macro-F1"),
        ("accuracy", "Accuracy"),
        ("macro_precision", "Macro Precision"),
        ("macro_recall", "Macro Recall"),
        ("cross_entropy", "Unweighted BCE"),
    ]
    for ax, (key, label) in zip(axes.flat, panels, strict=False):
        for split, name in (("train_real", "Train real"), ("valid", "Validation")):
            ax.plot(epochs, [row[split][key] for row in history], label=name)
        ax.axvline(summary["best_epoch"], color="gray", linestyle=":", label="Selected epoch")
        ax.set_title(label)
        ax.set_xlabel("Epoch")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    axes[1, 2].plot(epochs, [row["train_loss"] for row in history], label="Weighted SAM train loss")
    axes[1, 2].set_title("Optimization loss (different from unweighted BCE)")
    axes[1, 2].set_xlabel("Epoch")
    axes[1, 2].xaxis.set_major_locator(MaxNLocator(integer=True))
    axes[1, 2].grid(alpha=0.2)
    axes[1, 2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(report / "learning-curves.png", dpi=160)
    plt.close(fig)
    lines = [
        f"# {contract['task']} 직접 이진 모델 실험",
        "",
        "## 데이터 규모",
        "",
        "| Split | 인물 | ROI | 원본 등급별 ROI | 양호 / 유의 |",
        "|---|---:|---:|---|---|",
    ]
    for split, row in contract["splits"].items():
        lines.append(
            f"| {split} | {row['subjects']} | {row['roi']} | {row['grades']} | {row['binary']} |"
        )
    lines += [
        "",
        "## 설정",
        "",
        "```json",
        json.dumps(contract, ensure_ascii=False, indent=2),
        "```",
        "",
        f"종료 {summary['epochs_run']} epoch, 선택 {summary['best_epoch']} epoch. "
        "Validation Macro-F1 우선, 동률 시 BCE 최소. "
        "Test는 checkpoint 선택에 사용하지 않았다.",
        "",
        "## 최적 checkpoint 지표",
        "",
        "| Split | Accuracy | Macro P | Macro R | Macro-F1 | BCE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    selected = history[summary["best_epoch"] - 1]
    for split, row in (
        ("Train real", selected["train_real"]),
        ("Validation", summary["best_validation"]),
        ("Test", test),
    ):
        lines.append(
            f"| {split} | {row['accuracy']:.4f} | {row['macro_precision']:.4f} | "
            f"{row['macro_recall']:.4f} | {row['macro_f1']:.4f} | "
            f"{row['cross_entropy']:.4f} |"
        )
    lines += [
        "",
        "![Epoch별 학습 곡선](learning-curves.png)",
        "",
        "## Test 클래스 지표",
        "",
        "| 클래스 | 표본 | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in test["per_class"]:
        lines.append(
            f"| {row['name']} | {row['support']} | {row['precision']:.4f} | "
            f"{row['recall']:.4f} | {row['f1']:.4f} |"
        )
    lines += [
        "",
        f"혼동행렬 (행=정답, 열=예측; 양호/유의): `{test['confusion']}`",
        "",
        "## 원본 등급별 유의 예측률",
        "",
        "0~2등급에서는 유의로 잘못 예측한 비율이며, 3등급 이상에서는 유의 Recall이다.",
        "",
        "| 원본 등급 | 표본 | 유의 예측률 |",
        "|---:|---:|---:|",
    ]
    for row in test["per_original_grade"]:
        value = row["predicted_caution_rate"]
        lines.append(
            f"| {row['grade']} | {row['support']} | {value:.4f} |"
            if value is not None
            else f"| {row['grade']} | 0 | 미정 |"
        )
    lines += [
        "",
        "결과는 원본 인물 라벨과 현재 고정 분할에 대한 탐색 지표다. "
        "같은 인물의 여러 ROI는 독립된 인물 표본이 아니다.",
    ]
    (report / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
