"""Train BPR-MF and compare it with the models on a saved AR palette holdout."""

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from ml.scripts.run_ar_palette_bpr import (
    comparison_pairs,
    merit,
    parameter_grid,
    ranking_metrics,
    read_json,
    sigmoid,
    temporal_split,
    write_json,
)

BASE_MODELS = ("classifier", "learnbpr", "pairlogit")
MF_GRID = {
    "factors": (8, 16),
    "learning_rate": (0.01, 0.04),
    "regularization": (
        {"user": 0.001, "positive": 0.001, "negative": 0.0001},
        {"user": 0.05, "positive": 0.05, "negative": 0.005},
    ),
    "updates_per_pair": (30, 60),
}


@dataclass(frozen=True)
class IndexedTriplets:
    users: dict[str, int]
    items: dict[tuple[str, str], int]
    triplets: np.ndarray


def item_key(row):
    return row["product_id"], row["shade_id"]


def index_triplets(rows):
    pairs, _ = comparison_pairs(rows)
    if not pairs:
        raise ValueError("BPR-MF needs exposed cart/non-cart pairs")
    users, items, triplets = {}, {}, []
    for first, second in pairs:
        positive, negative = rows[first], rows[second]
        preferred_key, other_key = item_key(positive), item_key(negative)
        if preferred_key == other_key or positive["member"] != negative["member"]:
            raise ValueError("A triplet must compare two distinct items for the same user")
        user = users.setdefault(positive["member"], len(users))
        preferred = items.setdefault(preferred_key, len(items))
        other = items.setdefault(other_key, len(items))
        triplets.append((user, preferred, other))
    return IndexedTriplets(users, items, np.array(triplets, dtype=np.intp))


def fit_bpr_mf(data, parameters, seed):
    rng = np.random.default_rng(seed)
    dimensions = parameters["factors"]
    users = rng.normal(0, 0.1, (len(data.users), dimensions))
    items = rng.normal(0, 0.1, (len(data.items), dimensions))
    learning_rate = parameters["learning_rate"]
    regularization = parameters["regularization"]
    updates = len(data.triplets) * parameters["updates_per_pair"]

    # LearnBPR samples triples uniformly with replacement. Use the three vectors
    # from before the update to compute the BPR-MF gradients.
    for draw in rng.integers(len(data.triplets), size=updates):
        user, positive, negative = data.triplets[draw]
        user_vector = users[user].copy()
        item_difference = items[positive] - items[negative]
        factor = sigmoid(-float(user_vector @ item_difference))
        users[user] += learning_rate * (
            factor * item_difference - regularization["user"] * user_vector
        )
        items[positive] += learning_rate * (
            factor * user_vector - regularization["positive"] * items[positive]
        )
        items[negative] += learning_rate * (
            -factor * user_vector - regularization["negative"] * items[negative]
        )
    return users, items


def predict(data, factors, rows):
    users, items = factors
    scores = np.zeros(len(rows))
    for index, row in enumerate(rows):
        user_index = data.users.get(row["member"])
        item_index = data.items.get(item_key(row))
        if user_index is not None and item_index is not None:
            scores[index] = users[user_index] @ items[item_index]
    return scores


def factor_coverage(data, rows):
    known_users = [row["member"] in data.users for row in rows]
    known_items = [item_key(row) in data.items for row in rows]
    supported = [user and item for user, item in zip(known_users, known_items, strict=True)]
    pairs, _ = comparison_pairs(rows)
    return {
        "impressions": len(rows),
        "impressions_with_both_factors": sum(supported),
        "impressions_missing_user_factor": len(rows) - sum(known_users),
        "impressions_missing_item_factor": len(rows) - sum(known_items),
        "cart_pairs": len(pairs),
        "cart_pairs_with_both_scores_supported": sum(
            supported[positive] and supported[negative] for positive, negative in pairs
        ),
    }


def load_holdout(base_run):
    dataset = base_run / "dataset.json"
    baseline = read_json(base_run / "results.json")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if digest != baseline["dataset_sha256"]:
        raise ValueError("The dataset differs from the saved three-model experiment")

    train, validation, test, cutoffs = temporal_split(read_json(dataset)["rows"])
    test_ids = [row["impression_id"] for row in test]
    if cutoffs != baseline["cutoffs"] or test_ids != baseline["test_impression_ids"]:
        raise ValueError("The chronological holdout differs from the saved experiment")
    return baseline, train, validation, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_run", type=Path, help="Saved three-model experiment directory")
    parser.add_argument("output", type=Path, help="New directory for the MF model and results")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output directory")
    baseline, train, validation, test = load_holdout(args.base_run)
    seed = baseline["seed"]

    comparison = {}
    for name in BASE_MODELS:
        metrics = ranking_metrics(test, baseline["test_scores"][name])
        if metrics != baseline["models"][name]["test"]:
            raise ValueError(f"Saved metrics no longer match the test predictions for {name}")
        comparison[name] = metrics

    indexed_train = index_triplets(train)
    trials = []
    for parameters in parameter_grid(MF_GRID):
        factors = fit_bpr_mf(indexed_train, parameters, seed)
        scores = predict(indexed_train, factors, validation)
        trials.append({"parameters": parameters, "metrics": ranking_metrics(validation, scores)})
    selected = max(trials, key=lambda trial: merit(trial["metrics"]))

    development = index_triplets(train + validation)
    if (
        len(indexed_train.triplets) != baseline["training_cart_pairs"]
        or len(development.triplets) != baseline["development_cart_pairs"]
    ):
        raise ValueError("The training pairs differ from the saved experiment")
    user_factors, item_factors = fit_bpr_mf(development, selected["parameters"], seed)
    scores = predict(development, (user_factors, item_factors), test)
    comparison["bpr_mf"] = ranking_metrics(test, scores)
    coverage = factor_coverage(development, test)

    args.output.mkdir(parents=True)
    write_json(
        args.output / "model.json",
        {
            "model": "bpr_mf",
            "seed": seed,
            "parameters": selected["parameters"],
            "dataset_sha256": baseline["dataset_sha256"],
            "unknown_id_score": 0.0,
            "users": {
                user: user_factors[index].tolist() for user, index in development.users.items()
            },
            "items": [
                {"product_id": key[0], "shade_id": key[1], "factors": item_factors[index].tolist()}
                for key, index in development.items.items()
            ],
        },
    )
    write_json(
        args.output / "results.json",
        {
            "base_run": args.base_run.as_posix(),
            "dataset_sha256": baseline["dataset_sha256"],
            "cutoffs": baseline["cutoffs"],
            "splits": baseline["splits"],
            "test_impression_ids": baseline["test_impression_ids"],
            "seed": seed,
            "selected": selected,
            "validation_trials": trials,
            "training_triplets": len(indexed_train.triplets),
            "refit_triplets": len(development.triplets),
            "test_factor_coverage": coverage,
            "test_scores_bpr_mf": scores.tolist(),
            "test_comparison": comparison,
        },
    )
    for name, metrics in comparison.items():
        print(name, metrics["ndcg_at_3"], metrics["user_auc"])
    print("BPR-MF settings", selected["parameters"])
    print("BPR-MF test factor coverage", coverage)


if __name__ == "__main__":
    main()
