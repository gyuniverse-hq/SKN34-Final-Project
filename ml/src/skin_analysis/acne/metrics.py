"""Binary metrics include BOTH classes in macro F1; positive class is acne."""

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    auc,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)


def binary_metrics(targets, scores, threshold=.5):
    targets, scores = np.asarray(targets).reshape(-1), np.asarray(scores).reshape(-1)
    if (len(targets) == 0 or targets.shape != scores.shape
            or not np.isin(targets, [0, 1]).all() or not np.isfinite(scores).all()
            or (scores < 0).any() or (scores > 1).any() or not 0 < threshold < 1):
        raise ValueError("Nonempty binary labels, aligned finite scores and threshold required")
    predictions = scores >= threshold
    precision, recall, f1, support = precision_recall_fscore_support(
        targets, predictions, labels=[0, 1], zero_division=0)
    both = len(set(targets)) == 2
    p, r, _ = precision_recall_curve(targets, scores) if both else (None, None, None)
    return {
        "n": len(targets), "threshold": float(threshold),
        "accuracy": float(accuracy_score(targets, predictions)),
        "precision_acne": float(precision[1]), "recall_acne": float(recall[1]),
        "macro_f1": float(f1.mean()), "roc_auc": float(roc_auc_score(targets, scores))
        if both else None,
        "average_precision": float(average_precision_score(targets, scores)) if both else None,
        "pr_auc_trapezoid": float(auc(r, p)) if both else None,
        "confusion_matrix": confusion_matrix(targets, predictions, labels=[0, 1]).tolist(),
        "per_class": [{"label": i, "precision": float(precision[i]),
                       "recall": float(recall[i]), "f1": float(f1[i]),
                       "support": int(support[i])} for i in (0, 1)],
    }


def choose_threshold(targets, scores):
    candidates = [(binary_metrics(targets, scores, float(t))["macro_f1"],
                   -round(abs(t - .5), 8), float(t)) for t in np.arange(5, 96) / 100]
    return max(candidates)[2]


def paired_bootstrap(targets, a, b, groups, iterations, seed):
    targets, a, b, groups = map(np.asarray, (targets, a, b, groups))
    unique = np.unique(groups)
    if len(unique) < 2 or len({len(x) for x in (targets, a, b, groups)}) != 1:
        raise ValueError("Aligned predictions and at least two groups required")
    indices = [np.flatnonzero(groups == g) for g in unique]
    rng, differences = np.random.default_rng(seed), []
    for _ in range(iterations):
        chosen = np.concatenate([indices[i] for i in rng.integers(0, len(unique), len(unique))])
        if len(np.unique(targets[chosen])) < 2:
            continue
        # B (NIA) minus A (ImageNet), with a fixed threshold for attribution.
        differences.append(float(f1_score(targets[chosen], b[chosen] >= .5,
                                           average="macro", labels=[0, 1], zero_division=0)
                                 - f1_score(targets[chosen], a[chosen] >= .5,
                                            average="macro", labels=[0, 1], zero_division=0)))
    return {"metric": "macro_f1_at_0.5_nia_minus_imagenet", "iterations": iterations,
            "valid_iterations": len(differences), "groups": len(unique),
            "difference_ci95": np.quantile(differences, [.025, .975]).tolist()
            if differences else None}
