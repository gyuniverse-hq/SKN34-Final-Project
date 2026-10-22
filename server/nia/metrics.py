"""Metrics use original grades / measurement units, never unlabelled selfies."""

import math
import statistics


def classification(truth, predicted, classes):
    if not truth or len(truth) != len(predicted):
        raise ValueError("Expected equally sized, nonempty labelled predictions")
    matrix = [[0] * classes for _ in range(classes)]
    for actual, prediction in zip(truth, predicted, strict=True):
        if any(type(v) is not int or not 0 <= v < classes for v in (actual, prediction)):
            raise ValueError("Grade outside the checkpoint output range")
        matrix[actual][prediction] += 1
    per_grade = []
    for grade in range(classes):
        support = sum(matrix[grade])
        count = sum(row[grade] for row in matrix)
        true_positive = matrix[grade][grade]
        precision = true_positive / count if count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_grade.append(dict(grade=grade, support=support, predicted=count,
                              precision=precision, recall=recall, f1=f1))
    errors = [abs(a - p) for a, p in zip(truth, predicted, strict=True)]
    return dict(n=len(truth), accuracy=errors.count(0) / len(errors),
                mae=statistics.mean(errors), within_one=sum(e <= 1 for e in errors) / len(errors),
                macro_f1=statistics.mean(g["f1"] for g in per_grade),
                per_grade=per_grade, confusion=matrix)


def regression(truth, predicted):
    if not truth or len(truth) != len(predicted):
        raise ValueError("Expected equally sized, nonempty labelled predictions")
    if not all(math.isfinite(v) for v in [*truth, *predicted]):
        raise ValueError("Non-finite measurement")
    errors = [a - p for a, p in zip(truth, predicted, strict=True)]
    correlation = None
    if len(truth) >= 2 and len(set(truth)) > 1 and len(set(predicted)) > 1:
        correlation = statistics.correlation(truth, predicted)
    return dict(n=len(truth), mae=statistics.mean(abs(e) for e in errors),
                rmse=math.sqrt(statistics.mean(e * e for e in errors)), pearson=correlation,
                truth=list(truth), predicted=list(predicted))


def timing(values):
    if not values:
        return None
    ordered = sorted(values)
    # Linear interpolation, equivalent to NumPy's default percentile method.
    position = (len(ordered) - 1) * .95
    low, high = math.floor(position), math.ceil(position)
    p95 = ordered[low] + (ordered[high] - ordered[low]) * (position - low)
    return dict(n=len(values), mean_ms=statistics.mean(values),
                p50_ms=statistics.median(values), p95_ms=p95, samples_ms=list(values))
