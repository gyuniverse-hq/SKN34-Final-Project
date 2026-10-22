import numpy as np
import pytest

from skin_analysis.metrics import classification_metrics, group_bootstrap, select_thresholds


def test_confusion_precision_recall_and_f1():
    y = np.array([[1, 1], [1, 0], [0, 1], [0, 0]])
    scores = np.array([[0.9, 0.9], [0.8, 0.7], [0.6, 0.8], [0.1, 0.1]])
    result = classification_metrics(y, scores, ["a", "b"])
    assert result["classes"][0]["confusion_matrix"] == [[1, 1], [0, 2]]
    assert result["classes"][0]["precision"] == pytest.approx(2 / 3)
    assert result["macro_f1"] == pytest.approx(0.8)
    assert result["micro_f1"] == pytest.approx(0.8)


def test_threshold_tie_uses_nearest_half():
    y = np.array([[0], [1]])
    assert select_thresholds(y, [[0.1], [0.9]]) == [0.5]
    assert select_thresholds(y, [[0.2], [0.4]]) == [0.4]


def test_no_positive_has_explicit_unavailable_metrics():
    result = classification_metrics([[0], [0]], [[0.3], [0.8]], ["a"])
    assert result["classes"][0]["average_precision"] is None
    assert result["classes"][0]["f1"] is None
    assert result["macro_ap_evaluable_classes"] == 0


def test_bootstrap_preserves_groups_and_is_deterministic():
    y = np.array([[1], [1], [0], [0]])
    scores = np.array([[0.9], [0.8], [0.1], [0.2]])
    baseline = np.full_like(scores, 0.5)
    args = (y, scores, baseline, ["a", "a", "b", "b"], [0.5], [0.5])
    first = group_bootstrap(*args, iterations=50)
    assert first == group_bootstrap(*args, iterations=50)
    assert first["groups"] == 2


def test_metrics_reject_invalid_scores():
    with pytest.raises(ValueError):
        classification_metrics([[1]], [[float("nan")]], ["a"])
