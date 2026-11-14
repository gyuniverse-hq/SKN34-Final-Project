"""Shared loading, validation-only selection and multilabel evaluation."""

import hashlib
import importlib.metadata
import json
import platform
import textwrap
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    hamming_loss,
    jaccard_score,
    multilabel_confusion_matrix,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)

PARTS = ("training", "validation", "test")


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_data(root, kind):
    meta = json.loads((root / "encoding_metadata.json").read_text(encoding="utf-8"))
    data, hashes, sources = {}, {}, set()
    other = "catboost" if kind == "random_forest" else "random_forest"
    models = meta.get("models", ["random_forest", "catboost"])
    if kind not in models:
        raise ValueError(f"Model data not exported: {kind}")
    for part in PARTS:
        path = root / kind / f"{part}.jsonl"
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        peers = (
            [
                json.loads(line)
                for line in (root / other / f"{part}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            if other in models
            else None
        )
        if (peers is not None and len(rows) != len(peers)) or len(rows) != meta[
            "counts"
        ][part]:
            raise ValueError("Model data row counts differ")
        for i, row in enumerate(rows):
            if peers is not None and (
                row["source"] != peers[i]["source"] or row["y"] != peers[i]["y"]
            ):
                raise ValueError("Model data alignment differs")
            if row["source"] in sources:
                raise ValueError("Duplicate source across splits")
            sources.add(row["source"])
        x = np.asarray(
            [
                r["x"]
                if kind == "random_forest"
                else [r["x"][k] for k in meta["feature_columns"]]
                for r in rows
            ],
            dtype=np.float32 if kind == "random_forest" else object,
        )
        y = np.asarray([r["y"] for r in rows], dtype=np.uint8)
        if y.shape != (len(rows), len(meta["labels"])) or not np.isin(y, [0, 1]).all():
            raise ValueError("Invalid multi-hot target")
        data[part] = (x, y, [r["source"] for r in rows])
        hashes[part] = hashlib.sha256(raw).hexdigest()
    if (data["training"][1].sum(axis=0) == 0).any():
        raise ValueError("A target is absent from training")
    return meta, data, hashes


def select_threshold(y, scores):
    trials = []
    for threshold in np.linspace(0.10, 0.80, 29):
        pred = scores >= threshold
        trials.append(
            {
                "threshold": float(threshold),
                "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
                "micro_f1": float(f1_score(y, pred, average="micro", zero_division=0)),
            }
        )
    best = max(
        trials, key=lambda r: (r["macro_f1"], r["micro_f1"], -abs(r["threshold"] - 0.5))
    )
    return best, trials


def evaluate(y, scores, threshold, labels):
    if scores.shape != y.shape or not np.isfinite(scores).all():
        raise ValueError("Invalid prediction shape or non-finite scores")
    pred = (scores >= threshold).astype(np.uint8)
    matrices = multilabel_confusion_matrix(y, pred)
    support = y.sum(axis=0)
    supported = support > 0
    result = {
        "threshold": float(threshold),
        "samples": len(y),
        "label_count": y.shape[1],
        "supported_label_count": int(supported.sum()),
    }
    for average in ("micro", "macro", "weighted", "samples"):
        p, r, f, _ = precision_recall_fscore_support(
            y, pred, average=average, zero_division=0
        )
        result.update(
            {
                f"precision_{average}": float(p),
                f"recall_{average}": float(r),
                f"f1_{average}": float(f),
            }
        )
    p, r, f, _ = precision_recall_fscore_support(
        y[:, supported], pred[:, supported], average="macro", zero_division=0
    )
    result.update(
        {
            "precision_macro_supported": float(p),
            "recall_macro_supported": float(r),
            "f1_macro_supported": float(f),
            "subset_accuracy": float(accuracy_score(y, pred)),
            "hamming_loss": float(hamming_loss(y, pred)),
            "jaccard_samples": float(
                jaccard_score(y, pred, average="samples", zero_division=0)
            ),
            "average_precision_micro": float(
                average_precision_score(y, scores, average="micro")
            ),
            "average_precision_macro_supported": float(
                average_precision_score(
                    y[:, supported], scores[:, supported], average="macro"
                )
            ),
            "true_labels_per_row": float(y.sum(axis=1).mean()),
            "predicted_labels_per_row": float(pred.sum(axis=1).mean()),
        }
    )
    both = supported & (support < len(y))
    result["roc_auc_macro_supported"] = (
        float(roc_auc_score(y[:, both], scores[:, both], average="macro"))
        if both.any()
        else None
    )
    order = np.argsort(-scores, axis=1, kind="stable")
    for k in (3, 5):
        actual_k = min(k, y.shape[1])
        hits = np.take_along_axis(y, order[:, :actual_k], axis=1).sum(axis=1)
        result[f"precision_at_{k}"] = float((hits / actual_k).mean())
        result[f"recall_at_{k}"] = float((hits / np.maximum(1, y.sum(axis=1))).mean())
    per_p, per_r, per_f, _ = precision_recall_fscore_support(
        y, pred, average=None, zero_division=0
    )
    per_label = []
    for i, label in enumerate(labels):
        tn, fp, fn, tp = matrices[i].ravel()
        per_label.append(
            {
                **label,
                "support": int(support[i]),
                "precision": float(per_p[i]),
                "recall": float(per_r[i]),
                "f1": float(per_f[i]),
                "tn": int(tn),
                "fp": int(fp),
                "fn": int(fn),
                "tp": int(tp),
            }
        )
    return result, per_label, matrices, pred


def plot_results(folder, name, y, scores, matrices, labels, trials):
    if any(f.name == "Malgun Gothic" for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    total = matrices.sum(axis=0)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, values, title, fmt in (
        (axes[0], total, "전체 성분 집계 (건수)", "d"),
        (
            axes[1],
            total / np.maximum(1, total.sum(axis=1, keepdims=True)),
            "실제 라벨별 정규화",
            ".3f",
        ),
    ):
        ax.imshow(values, cmap="Blues")
        for (i, j), value in np.ndenumerate(values):
            ax.text(
                j,
                i,
                format(value, fmt),
                ha="center",
                va="center",
                color="white" if value > values.max() / 2 else "black",
            )
        ax.set(
            xticks=[0, 1],
            yticks=[0, 1],
            xticklabels=["미추천(0)", "추천(1)"],
            yticklabels=["미추천(0)", "추천(1)"],
            xlabel="예측",
            ylabel="실제",
            title=title,
        )
    fig.suptitle(f"{name} · 테스트 혼동행렬 (다중 라벨)")
    fig.tight_layout()
    fig.savefig(folder / "confusion_matrix.png", dpi=160)
    plt.close(fig)
    for start in range(0, len(labels), 20):
        fig, axes = plt.subplots(5, 4, figsize=(16, 19))
        for j, ax in enumerate(axes.flat):
            i = start + j
            if i >= len(labels):
                ax.axis("off")
                continue
            matrix = matrices[i]
            ax.imshow(matrix, cmap="Blues")
            for (r, c), value in np.ndenumerate(matrix):
                ax.text(
                    c,
                    r,
                    str(value),
                    ha="center",
                    va="center",
                    color="white" if value > matrix.max() / 2 else "black",
                )
            ax.set(
                xticks=[0, 1],
                yticks=[0, 1],
                xlabel="예측",
                ylabel="실제",
                title=(
                    textwrap.fill(
                        f"{labels[i]['db_id']} · {labels[i]['name']}", width=18
                    )
                    + f"\n정답 양성 {int(y[:, i].sum())}건"
                ),
            )
            ax.title.set_fontsize(9)
        fig.suptitle(
            f"{name} · 성분별 혼동행렬 {start + 1}–{min(start + 20, len(labels))}"
        )
        fig.tight_layout(rect=(0, 0, 1, 0.98))
        fig.savefig(folder / f"confusion_labels_{start // 20 + 1}.png", dpi=130)
        plt.close(fig)
    p, r, _ = precision_recall_curve(y.ravel(), scores.ravel())
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(r, p)
    axes[0].set(
        xlabel="Recall",
        ylabel="Precision",
        title="테스트 micro PR 곡선",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    axes[1].plot([t["threshold"] for t in trials], [t["macro_f1"] for t in trials])
    axes[1].set(xlabel="Threshold", ylabel="Macro-F1", title="검증 데이터 임계값 선택")
    fig.tight_layout()
    fig.savefig(folder / "precision_recall.png", dpi=160)
    plt.close(fig)


def finish_run(
    folder,
    name,
    model_config,
    meta,
    data,
    hashes,
    val_scores,
    test_scores,
    trials,
    threshold,
    fit_seconds,
):
    metrics = {}
    for part, scores in (("validation", val_scores), ("test", test_scores)):
        metrics[part], per_label, matrices, pred = evaluate(
            data[part][1], scores, threshold, meta["labels"]
        )
        write_json(folder / f"{part}_per_label.json", per_label)
        np.savez_compressed(
            folder / f"{part}_predictions.npz",
            y_true=data[part][1],
            probabilities=scores,
            y_pred=pred,
            sources=np.asarray(data[part][2]),
        )
        if part == "test":
            plot_results(
                folder, name, data[part][1], scores, matrices, meta["labels"], trials
            )
    write_json(folder / "metrics.json", metrics)
    write_json(
        folder / "selection.json",
        {
            "config": model_config,
            "threshold": threshold,
            "threshold_trials": trials,
            "fit_seconds": fit_seconds,
        },
    )
    versions = {
        p: importlib.metadata.version(p)
        for p in ("numpy", "scikit-learn", "matplotlib", "tqdm")
    }
    if name == "CatBoost":
        versions["catboost"] = importlib.metadata.version("catboost")
    write_json(
        folder / "provenance.json",
        {
            "input_hashes": hashes,
            "python": platform.python_version(),
            "versions": versions,
            "labels": meta["labels"],
            "test_used_for_selection": False,
        },
    )
    metrics_table = ["| 지표 | 검증 | 테스트 |", "| --- | ---: | ---: |"]
    keys = [
        "precision_micro",
        "recall_micro",
        "f1_micro",
        "precision_macro",
        "recall_macro",
        "f1_macro",
        "f1_macro_supported",
        "f1_weighted",
        "f1_samples",
        "subset_accuracy",
        "hamming_loss",
        "jaccard_samples",
        "average_precision_micro",
        "average_precision_macro_supported",
        "precision_at_3",
        "recall_at_3",
        "precision_at_5",
        "recall_at_5",
    ]
    for key in keys:
        metrics_table.append(
            f"| {key} | {metrics['validation'][key]:.4f} | {metrics['test'][key]:.4f} |"
        )
    test = metrics["test"]
    lines = [
        f"# {name} 추천 성분 학습 결과",
        "",
        (
            f"학습 {len(data['training'][1]):,}건 / 검증 {len(data['validation'][1]):,}건 / "
            f"테스트 {len(data['test'][1]):,}건. Y는 {len(meta['labels'])}종 멀티핫이다."
        ),
        "",
        (
            f"검증 macro-F1로 설정과 공통 임계값 {threshold:.3f}을 선택했다. "
            f"테스트는 설정 선택 후에만 평가했다. 학습·검증 선택 소요 시간 {fit_seconds:.1f}초."
        ),
        "",
        *metrics_table,
        "",
        (
            "macro는 전체 80종을 동일 가중 평균하며, 정답·예측이 모두 없는 성분도 0으로 계산한다. "
            "macro_supported는 해당 구간에 정답 양성이 존재하는 성분만 평균한다. "
            "weighted는 정답 양성 건수 가중 평균, samples는 답변 단위 평균이다. "
            "Hamming loss는 낮을수록 좋다. "
            "subset_accuracy는 한 답변의 성분 집합이 모두 맞은 비율이다."
        ),
        "",
        (
            f"테스트에 실제 등장한 성분은 {test['supported_label_count']}종이다. "
            "등장하지 않은 성분의 개별 성능은 평가할 수 없다. "
            f"실제 성분 수 평균 {test['true_labels_per_row']:.2f}, "
            f"예측 성분 수 평균 {test['predicted_labels_per_row']:.2f}."
        ),
        "",
        (
            "0은 원본 답변에서 미추천을 의미하며 임상적 부적합 판정이 아니다. "
            "원문과 사용자 정규화로 만든 정답에 대한 일치도를 측정하며 "
            "독립적인 전문가 검증 결과가 아니다."
        ),
        "",
        "## 혼동행렬",
        "",
        (
            "다중 라벨이므로 성분별 2×2 행렬을 사용한다. "
            "합산 행렬의 표본 단위는 사람 수가 아니라 레코드×성분의 이진 판단이다. "
            "TN이 많아 단순 정확도만으로 성능을 판단하지 않는다."
        ),
        "",
        "![전체 혼동행렬](confusion_matrix.png)",
        "",
        "![PR 곡선](precision_recall.png)",
        "",
        "## 성분별 지표",
        "",
        "| DB ID | 성분 | 테스트 양성 건수 | Precision | Recall | F1 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    per_label = json.loads((folder / "test_per_label.json").read_text(encoding="utf-8"))
    for item in sorted(per_label, key=lambda x: (-x["support"], x["db_id"])):
        lines.append(
            f"| {item['db_id']} | {item['name']} | {item['support']} | "
            f"{item['precision']:.4f} | {item['recall']:.4f} | {item['f1']:.4f} |"
        )
    lines.extend(["", "## 전체 성분별 혼동행렬", ""])
    for i in range(1, 5):
        lines.extend([f"![성분별 혼동행렬 {i}](confusion_labels_{i}.png)", ""])
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"model": name, "test": metrics["test"]}, ensure_ascii=False, indent=2
        ),
        flush=True,
    )


def feature_summary(data):
    x, y, _ = data["training"]
    groups = {}
    for features, labels in zip(x.tolist(), y.tolist(), strict=True):
        groups.setdefault(tuple(features), set()).add(tuple(labels))
    return {
        "training_unique_x": len(groups),
        "training_x_with_different_y": sum(len(v) > 1 for v in groups.values()),
        "training_label_support": Counter(
            {str(i): int(v) for i, v in enumerate(y.sum(axis=0))}
        ),
    }
