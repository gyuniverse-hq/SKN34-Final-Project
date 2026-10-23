"""Render the frozen report/predictions without rerunning inference or selecting models."""

import argparse
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve, roc_curve

from .common import load_config, read_json


def plot(config):
    settings = config["train"]
    root = Path(settings["output"])
    folder = root / f"comparison-seed-{settings['seed']}"
    report = read_json(folder / "report.json")
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), constrained_layout=True)
    colors = {"imagenet": "#3066be", "nia": "#c75037"}
    for column, source in enumerate(("imagenet", "nia")):
        result = report["experiments"][source]
        matrix = np.array(result["metrics"]["test"]["fixed_05"]["confusion_matrix"])
        axis = axes[0, column]
        axis.imshow(matrix, cmap="Blues")
        for (i, j), value in np.ndenumerate(matrix):
            axis.text(j, i, str(value), ha="center", va="center", fontsize=18,
                      color="white" if value > matrix.max() / 2 else "black")
        axis.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Normal", "Acne"],
                 yticklabels=["Normal", "Acne"], xlabel="Predicted", ylabel="Actual",
                 title=f"{source}: internal test, threshold=0.5")
        rows = [r for r in read_json(folder / f"{source}-predictions.json") if r["split"] == "test"]
        truth, scores = [r["label"] for r in rows], [r["score"] for r in rows]
        fpr, tpr, _ = roc_curve(truth, scores)
        precision, recall, _ = precision_recall_curve(truth, scores)
        axes[0, 2].plot(fpr, tpr, label=source, color=colors[source])
        axes[1, 0].plot(recall, precision, label=source, color=colors[source])
        history = read_json(root / f"{source}-seed-{settings['seed']}" / "history.json")
        epoch = [r["epoch"] for r in history]
        axes[1, 1].plot(epoch, [r["validation"]["macro_f1"] for r in history],
                        label=source, color=colors[source])
        values = [result["metrics"][s]["fixed_05"]["macro_f1"]
                  for s in ("valid", "test", "official_audit")]
        axes[1, 2].bar(np.arange(3) + (column - .5) * .34, values, width=.34,
                       label=source, color=colors[source])
    axes[0, 2].plot([0, 1], [0, 1], "--", color="gray")
    axes[0, 2].set(title="Internal test ROC", xlabel="False positive rate", ylabel="Recall")
    axes[1, 0].set(title="Internal test PR", xlabel="Recall", ylabel="Precision")
    axes[1, 1].set(title="Validation Macro F1 at 0.5", xlabel="Epoch", ylabel="Macro F1")
    axes[1, 2].set(title="Synthetic domains, threshold=0.5", ylabel="Macro F1",
                   xticks=np.arange(3),
                   xticklabels=["Validation", "Internal test", "Official audit"])
    for axis in (axes[0, 2], *axes[1]):
        axis.legend()
        axis.grid(alpha=.2)
        axis.set_ylim(0, 1.03)
    fig.suptitle("Acne vs Normal: matched ResNet-50 initialization comparison\n"
                 "Synthetic data only; one seed; "
                 "person independence and real-photo accuracy unverified")
    fig.savefig(folder / "comparison.png", dpi=160)
    plt.close(fig)
    return folder / "comparison.png"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(plot(load_config(args.config) if args.config else load_config()))


if __name__ == "__main__":
    main()
