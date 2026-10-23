"""Metrics, validation-only threshold selection, and paired group bootstrap."""

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve


def validate_arrays(targets, scores):
    targets, scores = np.asarray(targets), np.asarray(scores, dtype=float)
    if targets.ndim != 2 or targets.shape != scores.shape or len(targets) == 0:
        raise ValueError("Expected nonempty matching [N,K] targets/scores")
    if not np.isin(targets, [0, 1]).all() or not np.isfinite(scores).all():
        raise ValueError("Targets must be binary and scores finite")
    if (scores < 0).any() or (scores > 1).any():
        raise ValueError("Expected sigmoid scores in [0,1]")
    return targets.astype(int), scores


def f1_from_counts(tp, fp, fn):
    return np.divide(
        2 * tp, 2 * tp + fp + fn, out=np.zeros_like(tp, dtype=float), where=(2 * tp + fp + fn) > 0
    )


def threshold_f1(targets, scores, thresholds):
    predictions = scores >= np.asarray(thresholds)
    tp = np.sum(predictions & (targets == 1), axis=0)
    fp = np.sum(predictions & (targets == 0), axis=0)
    fn = np.sum(~predictions & (targets == 1), axis=0)
    return f1_from_counts(tp, fp, fn)


def select_thresholds(targets, scores) -> list[float]:
    targets, scores = validate_arrays(targets, scores)
    result = []
    for index in range(targets.shape[1]):
        if len(set(targets[:, index])) != 2:
            result.append(0.5)
            continue
        candidates = []
        for threshold in np.arange(5, 96) / 100:
            f1 = threshold_f1(
                targets[:, index : index + 1], scores[:, index : index + 1], threshold
            )[0]
            candidates.append((float(f1), -round(abs(threshold - 0.5), 8), float(threshold)))
        result.append(max(candidates)[2])
    return result


def classification_metrics(targets, scores, classes: list[str], thresholds=0.5) -> dict:
    targets, scores = validate_arrays(targets, scores)
    if targets.shape[1] != len(classes):
        raise ValueError("Class count differs from prediction columns")
    thresholds = np.broadcast_to(np.asarray(thresholds, dtype=float), (len(classes),))
    if not np.isfinite(thresholds).all() or (thresholds < 0).any() or (thresholds > 1).any():
        raise ValueError("Invalid thresholds")
    predictions = scores >= thresholds
    rows, aps = [], []
    total_tp = total_fp = total_fn = 0
    for index, name in enumerate(classes):
        actual, predicted = targets[:, index].astype(bool), predictions[:, index]
        tp, fp = int(np.sum(actual & predicted)), int(np.sum(~actual & predicted))
        fn, tn = int(np.sum(actual & ~predicted)), int(np.sum(~actual & ~predicted))
        positive, negative = int(actual.sum()), int((~actual).sum())
        evaluable = positive > 0 and negative > 0
        ap = float(average_precision_score(actual, scores[:, index])) if evaluable else None
        if ap is not None:
            aps.append(ap)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / positive if positive else None
        f1 = 2 * tp / (2 * tp + fp + fn) if positive else None
        curve = None
        if evaluable:
            p, r, cutoffs = precision_recall_curve(actual, scores[:, index])
            curve = {"precision": p.tolist(), "recall": r.tolist(), "thresholds": cutoffs.tolist()}
        rows.append(
            {
                "class": name,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "positive_support": positive,
                "negative_support": negative,
                "confusion_matrix": [[tn, fp], [fn, tp]],
                "average_precision": ap,
                "average_precision_unavailable_reason": None
                if evaluable
                else "Both positive and negative targets are required",
                "false_positive_rate": fp / negative if negative else None,
                "threshold": float(thresholds[index]),
                "pr_curve": curve,
            }
        )
        total_tp += tp
        total_fp += fp
        total_fn += fn
    available_f1 = [row["f1"] for row in rows if row["f1"] is not None]
    denominator = 2 * total_tp + total_fp + total_fn
    return {
        "images": len(targets),
        "classes": rows,
        "macro_f1": float(np.mean(available_f1)) if available_f1 else None,
        "micro_f1": 2 * total_tp / denominator if denominator else 0.0,
        "macro_ap": float(np.mean(aps)) if aps else None,
        "macro_f1_evaluable_classes": len(available_f1),
        "macro_ap_evaluable_classes": len(aps),
    }


def group_bootstrap(
    targets,
    scores,
    baseline,
    groups,
    thresholds,
    baseline_thresholds,
    iterations: int = 1000,
    seed: int = 42,
) -> dict:
    targets, scores = validate_arrays(targets, scores)
    groups = np.asarray(groups)
    unique = np.unique(groups)
    if len(groups) != len(targets) or len(unique) < 2 or iterations < 1:
        raise ValueError("Bootstrap requires aligned groups, >=2 groups, and positive iterations")
    indices = [np.flatnonzero(groups == group) for group in unique]
    rng = np.random.default_rng(seed)
    values, differences = [], []
    for _ in range(iterations):
        sampled = np.concatenate([indices[i] for i in rng.integers(0, len(unique), len(unique))])
        y = targets[sampled]
        available = y.sum(axis=0) > 0
        if not available.any():
            continue
        model_f1 = threshold_f1(y, scores[sampled], thresholds)[available].mean()
        baseline_f1 = threshold_f1(y, baseline[sampled], baseline_thresholds)[available].mean()
        values.append(float(model_f1))
        differences.append(float(model_f1 - baseline_f1))
    return {
        "iterations": iterations,
        "valid_iterations": len(values),
        "groups": len(unique),
        "macro_f1_ci95": np.quantile(values, [0.025, 0.975]).tolist() if values else None,
        "macro_f1_difference_ci95": np.quantile(differences, [0.025, 0.975]).tolist()
        if differences
        else None,
    }
