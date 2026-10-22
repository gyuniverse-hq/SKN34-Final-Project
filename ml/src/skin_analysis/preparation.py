"""Reversible quarantine and support-constrained splitting; never relabel images."""

from collections import defaultdict

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from .config import SPLIT_RATIOS, SPLITS, positive_support_minima


def quarantine_records(records, source_records, duplicate_groups, near_pairs, settings):
    """Exclude whole known groups, preserving all original files and conflicting labels."""
    by_path = {record["path"]: record for record in source_records}
    reasons = defaultdict(set)
    conflicts = [
        paths
        for paths in duplicate_groups
        if len({tuple(by_path[path]["labels"]) for path in paths}) > 1
    ]
    if settings.get("quarantine_conflicts", False):
        for paths in conflicts:
            for path in paths:
                reasons[by_path[path]["group_id"]].add("conflicting_duplicate_labels")
    if settings.get("quarantine_unreviewed_similarities", False):
        for pair in near_pairs:
            for key in ("path_a", "path_b"):
                reasons[by_path[pair[key]]["group_id"]].add("unreviewed_similarity")
    kept = [record for record in records if record["group_id"] not in reasons]
    quarantined = [
        {
            **{
                key: record[key]
                for key in ("path", "original_split", "group_id", "labels", "sha256")
            },
            "reasons": sorted(reasons[record["group_id"]]),
        }
        for record in source_records
        if record["group_id"] in reasons
    ]
    unresolved = [
        paths
        for paths in conflicts
        if any(by_path[path]["group_id"] not in reasons for path in paths)
    ]
    remaining_near = [
        pair
        for pair in near_pairs
        if all(by_path[pair[key]]["group_id"] not in reasons for key in ("path_a", "path_b"))
    ]
    return kept, quarantined, unresolved, remaining_near


def resplit_records(records, seed, *, settings, classes, normal_index=None):
    """MILP allocates interchangeable *whole groups*, enforcing every minimum support.

    Groups with identical size/label-count/compound-count signatures share an integer
    allocation variable. This keeps thousands of singleton photos out of the MILP while
    preserving indivisible person/source groups. Seeded expansion chooses actual groups.
    """
    if any(
        len(record["labels"]) != len(classes)
        or any(value not in (0, 1) for value in record["labels"])
        for record in records
    ):
        raise ValueError("Cannot resplit incomplete or non-binary annotations")
    groups = defaultdict(list)
    for record in records:
        groups[record["group_id"]].append(record)
    if len(groups) < 10:
        raise ValueError("Group resplit requires at least ten independent groups")
    buckets = defaultdict(list)
    for group_id, group in sorted(groups.items()):
        positives = [sum(record["labels"][i] == 1 for record in group) for i in range(len(classes))]
        compound = sum(
            sum(value == 1 for i, value in enumerate(record["labels"]) if i != normal_index) >= 2
            for record in group
        )
        signature = (len(group), *positives, compound)
        buckets[signature].append(group_id)
    signatures = sorted(buckets)
    values = np.array(signatures, dtype=float)
    available = np.array([len(buckets[signature]) for signature in signatures])
    totals = available @ values
    required_negative = 1 + 2 * settings["min_eval_negative"]
    positive_minima = {}
    for i, name in enumerate(classes):
        positive, negative = int(totals[1 + i]), int(totals[0] - totals[1 + i])
        positive_minima[name] = positive_support_minima(settings, positive)
        required_positive = sum(positive_minima[name].values())
        if positive < required_positive or negative < required_negative:
            raise ValueError(
                f"Cannot split {name}: available positive={positive}, negative={negative}; "
                f"need at least {required_positive}/{required_negative} across splits"
            )
    if totals[-1] < sum(settings[f"min_compound_{split}"] for split in SPLITS):
        raise ValueError("Insufficient compound images to satisfy all split minima")
    ratios = SPLIT_RATIOS
    targets = [int(round(len(records) * ratio)) for ratio in ratios[:2]]
    targets.append(len(records) - sum(targets))
    # Integer count variables per signature/split, plus paired L1-deviation slack variables.
    base = len(signatures) * 3
    features = values.shape[1]
    variables = base + 3 * features * 2
    objective = np.zeros(variables)
    upper_bounds = np.full(variables, np.inf)
    integrality = np.zeros(variables)
    integrality[:base] = 1
    for bucket, count in enumerate(available):
        upper_bounds[bucket * 3 : bucket * 3 + 3] = count
    row_indices, column_indices, coefficients, lower, upper = [], [], [], [], []

    def add_row(terms, low=-np.inf, high=np.inf):
        row = len(lower)
        for column, value in terms.items():
            if value:
                row_indices.append(row)
                column_indices.append(column)
                coefficients.append(float(value))
        lower.append(low)
        upper.append(high)

    def terms_for(split_index, feature_values):
        return {
            bucket * 3 + split_index: value for bucket, value in enumerate(feature_values) if value
        }

    for bucket, count in enumerate(available):
        add_row({bucket * 3 + split: 1 for split in range(3)}, count, count)
    tolerance = int(values[:, 0].max()) - 1
    for split_index, (split, ratio) in enumerate(zip(SPLITS, ratios, strict=True)):
        add_row(
            terms_for(split_index, values[:, 0]),
            max(1, targets[split_index] - tolerance),
            targets[split_index] + tolerance,
        )
        add_row(terms_for(split_index, np.ones(len(signatures))), 1 if split == "train" else 2)
        min_neg = 1 if split == "train" else settings["min_eval_negative"]
        for i, name in enumerate(classes):
            min_pos = positive_minima[name][split]
            add_row(terms_for(split_index, values[:, 1 + i]), min_pos)
            add_row(terms_for(split_index, values[:, 0] - values[:, 1 + i]), min_neg)
        add_row(terms_for(split_index, values[:, -1]), settings[f"min_compound_{split}"])
        for feature in range(features):
            expected = targets[split_index] if feature == 0 else totals[feature] * ratio
            slack = base + (split_index * features + feature) * 2
            terms = terms_for(split_index, values[:, feature])
            terms[slack], terms[slack + 1] = -1, 1
            add_row(terms, expected, expected)
            weight = (10 if feature == 0 else 1) / max(expected, 1)
            objective[slack : slack + 2] = weight
    matrix = coo_array(
        (
            np.array(coefficients),
            (np.array(row_indices, dtype=np.int32), np.array(column_indices, dtype=np.int32)),
        ),
        shape=(len(lower), variables),
    ).tocsc()
    constraint = LinearConstraint(matrix, np.array(lower), np.array(upper))
    solution = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(np.zeros(variables), upper_bounds),
        constraints=constraint,
        options={"time_limit": 30.0, "mip_rel_gap": 1e-6},
    )
    if not solution.success:
        raise ValueError(
            "No proven feasible group split with all support minima: " + solution.message
        )
    allocations = np.rint(solution.x[:base]).astype(int).reshape(-1, 3)
    if np.max(np.abs(allocations.ravel() - solution.x[:base])) > 1e-6:
        raise ValueError("Split solver returned a nonintegral group assignment")
    checked = solution.x.copy()
    checked[:base] = allocations.ravel()
    actual = matrix @ checked
    if np.any(actual < np.array(lower) - 1e-5) or np.any(actual > np.array(upper) + 1e-5):
        raise ValueError("Split assignment violates support constraints")
    rng = np.random.default_rng(seed)
    for signature, allocation in zip(signatures, allocations, strict=True):
        group_ids = sorted(buckets[signature])
        rng.shuffle(group_ids)
        offset = 0
        for split, count in zip(SPLITS, allocation, strict=True):
            for group_id in group_ids[offset : offset + count]:
                for record in groups[group_id]:
                    record["split"] = split
            offset += count
    return {
        "algorithm": "signature-group-milp-v2",
        "seed": seed,
        "signature_buckets": len(signatures),
        "groups": len(groups),
        "target_images": dict(zip(SPLITS, targets, strict=True)),
        "positive_support_policy": settings.get("positive_support_policy", "fixed"),
        "positive_minima": positive_minima,
        "size_tolerance": tolerance,
        "objective": float(solution.fun),
    }
