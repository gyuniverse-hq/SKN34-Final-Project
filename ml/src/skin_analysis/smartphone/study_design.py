"""Deterministic study recipes, subject splits, and crossed paired bootstrap."""

import copy
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from .common import TASKS, assert_disjoint, digest
from .train import class_weights

WEIGHTINGS = (
    ("ce", 0.0, None),
    ("sqrt-cap2", 0.5, 2.0),
    ("sqrt-cap4", 0.5, 4.0),
    ("sqrt-uncapped", 0.5, None),
    ("inverse-cap4", 1.0, 4.0),
    ("inverse-uncapped", 1.0, None),
)
OPTIMIZERS = ("adamw", "sam_adamw")
LOSSES = (
    ("weighted_focal", {"focal_gamma": 1.0}),
    ("weighted_focal", {"focal_gamma": 2.0}),
    ("class_balanced_ce", {"cb_beta": 0.999}),
    ("class_balanced_focal", {"cb_beta": 0.999, "focal_gamma": 2.0}),
    ("weighted_ordinal_cdf", {}),
    ("coral", {}),
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def recipe_id(recipe):
    return digest(recipe)[:16]


def optimizer_recipe(recipe, optimizer):
    recipe = {k: v for k, v in recipe.items() if k not in ("optimizer", "sam_rho")}
    recipe["optimizer"] = optimizer
    if optimizer == "sam_adamw":
        recipe["sam_rho"] = 0.05
    return recipe


def factorial_recipes(records, task, batches=(16, 32)):
    labels = [r["truth"] for r in records if r["task"] == task and r["split"] == "train"]
    aliases = defaultdict(list)
    representatives = {}
    for name, exponent, cap in WEIGHTINGS:
        vector = tuple(class_weights(labels, TASKS[task]["classes"], cap, exponent).tolist())
        aliases[vector].append(name)
        representatives.setdefault(vector, (exponent, cap))
    rows = []
    for vector, (exponent, cap) in representatives.items():
        for optimizer, batch in itertools.product(OPTIMIZERS, batches):
            recipe = optimizer_recipe(
                dict(
                    backbone="resnet50",
                    loss="unweighted_cross_entropy" if exponent == 0 else "weighted_cross_entropy",
                    weight_exponent=exponent,
                    class_weight_cap=cap,
                    batch_size=batch,
                    lr_multiplier=1.0,
                ),
                optimizer,
            )
            rows.append(dict(recipe=recipe, aliases=aliases[vector], weights=list(vector)))
    return rows


def loss_recipes(reference):
    for (loss, parameters), optimizer in itertools.product(LOSSES, OPTIMIZERS):
        recipe = {k: v for k, v in reference.items() if k not in ("focal_gamma", "cb_beta")}
        yield optimizer_recipe(recipe | dict(loss=loss) | parameters, optimizer)


def backbone_recipes(reference, backbones, multipliers):
    for backbone, optimizer, multiplier in itertools.product(backbones, OPTIMIZERS, multipliers):
        yield optimizer_recipe(
            reference | dict(backbone=backbone, lr_multiplier=multiplier), optimizer
        )


def split_manifest(source, fold, *, split_seed=42, outer_folds=3, inner_folds=5):
    """Old test groups never enter this manifest, including its outer-test partition."""
    original_test = {r["group"] for r in source["records"] if r["split"] == "test"}
    records = [r for r in source["records"] if r["split"] != "test"]
    if original_test & {r["group"] for r in records}:
        raise ValueError("Original test overlaps development subjects")
    labels = [f"{r['task']}:{r['truth']}" for r in records]
    groups = [r["group"] for r in records]
    outer = StratifiedGroupKFold(outer_folds, shuffle=True, random_state=split_seed)
    partitions = list(outer.split(np.zeros(len(records)), labels, groups))
    training_indices, evaluation_indices = partitions[fold]
    inner = StratifiedGroupKFold(inner_folds, shuffle=True, random_state=split_seed + fold)
    inner_train, inner_valid = next(
        inner.split(
            np.zeros(len(training_indices)),
            [labels[i] for i in training_indices],
            [groups[i] for i in training_indices],
        )
    )
    owners = {records[i]["group"]: "test" for i in evaluation_indices}
    owners.update({groups[training_indices[i]]: "train" for i in inner_train})
    owners.update({groups[training_indices[i]]: "valid" for i in inner_valid})
    result = copy.deepcopy(source)
    result.pop("fingerprint", None)
    result["records"] = [{**r, "split": owners[r["group"]]} for r in records]
    assert_disjoint(result["records"])
    result["source_fingerprint"] = source["fingerprint"]
    result["study_fold"] = fold
    result["split_method"] = "development-only outer SGKF3 / inner SGKF5 fold0"
    result["settings"] = dict(
        split_seed=split_seed, outer_folds=outer_folds, inner_folds=inner_folds
    )
    result["summary"] = {}
    for task, specification in TASKS.items():
        result["summary"][task] = {}
        for split in ("train", "valid", "test"):
            selected = [r for r in result["records"] if r["task"] == task and r["split"] == split]
            counts = np.bincount([r["truth"] for r in selected], minlength=specification["classes"])
            if (counts == 0).any():
                raise ValueError(f"Missing grade in preregistered fold {fold}/{task}/{split}")
            result["summary"][task][split] = dict(
                n=len(selected),
                subjects=len({r["subject"] for r in selected}),
                grade_support=counts.tolist(),
            )
    result["fingerprint"] = digest(result)
    return result


def f1_from_confusion(matrix):
    matrix = np.asarray(matrix)
    tp = np.diagonal(matrix, axis1=-2, axis2=-1)
    denominator = matrix.sum(-1) + matrix.sum(-2)
    return np.divide(
        2 * tp, denominator, out=np.zeros_like(tp, dtype=float), where=denominator != 0
    ).mean(-1)


def prediction_cube(predictions, classes):
    """[seed, independent group, truth, prediction]; align by private ROI IDs."""
    seeds = sorted(predictions)
    reference = sorted(predictions[seeds[0]], key=lambda r: r["id"])
    groups = sorted({r["group"] for r in reference})
    group_index = {group: i for i, group in enumerate(groups)}
    identities = [(r["id"], r["group"], r["truth"]) for r in reference]
    cube = np.zeros((len(seeds), len(groups), classes, classes), dtype=np.int32)
    for index, seed in enumerate(seeds):
        rows = sorted(predictions[seed], key=lambda r: r["id"])
        if [(r["id"], r["group"], r["truth"]) for r in rows] != identities:
            raise ValueError("Candidate seed predictions do not align")
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError("Repeated out-of-fold ROI")
        for row in rows:
            cube[index, group_index[row["group"]], row["truth"], row["predicted"]] += 1
    return cube, (seeds, identities)


def paired_bootstrap(left, right, *, samples=10000, seed=4242):
    """Crossed resampling: the same seed/group draws apply to both candidates."""
    if left.shape != right.shape or not left.size or samples < 1:
        raise ValueError("Aligned nonempty prediction cubes and positive samples required")
    rng = np.random.default_rng(seed)
    n_seeds, n_groups = left.shape[:2]
    differences = []
    for offset in range(0, samples, 100):
        batch = min(100, samples - offset)
        group_counts = rng.multinomial(n_groups, np.full(n_groups, 1 / n_groups), size=batch)
        seed_indices = rng.integers(n_seeds, size=(batch, n_seeds))
        scores = []
        for cube in (left, right):
            matrices = np.einsum("bg,sgij->bsij", group_counts, cube, optimize=True)
            f1 = f1_from_confusion(matrices)
            scores.append(np.take_along_axis(f1, seed_indices, axis=1).mean(1))
        differences.extend((scores[0] - scores[1]).tolist())
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return dict(
        difference=float(
            f1_from_confusion(left.sum(1)).mean() - f1_from_confusion(right.sum(1)).mean()
        ),
        lower=float(lower),
        upper=float(upper),
        samples=samples,
        interpretation="internal exploratory interval; not external confirmation",
    )
