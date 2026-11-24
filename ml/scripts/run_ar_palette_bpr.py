"""Run the offline AR palette ranking comparison on reproducible mock impressions."""

import argparse
import hashlib
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import product
from pathlib import Path

import catboost
import numpy as np
from catboost import CatBoostRanker, Pool

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "backend/api/seed/catalog.json"
sys.path.insert(0, str(ROOT / "backend/api"))

from app.core.ar_palette import (  # noqa: E402
    CATEGORICAL,
    FEATURE_VERSION,
    FEATURES,
    Shade,
    ShadeKey,
    score_inputs,
    shade_features,
    top_chips,
)
from app.core.ar_palette_artifacts import (  # noqa: E402
    feature_matrix,
    read_json,
    score_model,
    write_json,
)
from app.services.ar_palette_search import (  # noqa: E402
    FIXED_PARAMETERS,
    GRID_SPACE,
    SEED,
    fit_candidate,
    parameter_grid,
    training_pool,
)
from app.services.ar_palette_training_service import summarize, temporal_split  # noqa: E402

IMPRESSION_COUNT = 1000
MEMBER_COUNT = 120
ZONE_COUNTS = {"lip": 45, "blush": 30}
DISCOUNTS = tuple(1 / math.log2(rank + 1) for rank in range(1, 4))
BPR_GRID = {
    "learning_rate": (0.01, 0.04),
    "l2": (0.001, 0.05),
    "updates_per_pair": (5, 15, 30, 60),
}


def sigmoid(value):
    exponent = math.exp(-abs(value))
    return 1 / (1 + exponent) if value >= 0 else exponent / (1 + exponent)


def style_match(preferred, shade):
    return (
        0.42 * (preferred.family == shade.family)
        + 0.23 * (preferred.texture == shade.texture)
        + 0.23 * max(0.0, 1 - abs(preferred.lightness - shade.lightness) / 35)
        + 0.12 * max(0.0, 1 - abs(preferred.chroma - shade.chroma) / 50)
    )


def sampled_catalog(rng):
    eligible = defaultdict(list)
    for item in read_json(CATALOG)["products"]:
        zone = item.get("makeupZone")
        if zone not in ZONE_COUNTS:
            continue
        shades = {}
        for option in item.get("shades", []):
            shade = shade_features(
                option.get("hex"),
                item.get("texture"),
                option.get("measureMethod"),
                option.get("colorSource"),
            )
            if shade is not None:
                shades[(item["id"], option["id"])] = shade
        if shades:
            eligible[zone].append((item["id"], shades))

    catalogs, ratings = {}, {}
    for zone, count in ZONE_COUNTS.items():
        options = sorted(eligible[zone], key=lambda item: item[0])
        catalogs[zone], ratings[zone] = {}, {}
        for index in rng.choice(len(options), size=count, replace=False):
            product_id, shades = options[index]
            catalogs[zone].update(shades)
            # The seed catalog supplies shades. Ratings and review counts are synthetic.
            ratings[zone][product_id] = (
                round(4.05 + 0.94 * rng.beta(4, 2), 2),
                int(np.clip(rng.lognormal(5.8, 1.5), 14, 14000)),
            )
    return catalogs, ratings


@dataclass
class Profile:
    preferred: Shade
    intent: float
    daily: dict[tuple[ShadeKey, date], float] = field(default_factory=dict)

    def record(self, key, day, weight):
        self.daily[(key, day)] = max(weight, self.daily.get((key, day), 0.0))


@dataclass(frozen=True)
class MockRequest:
    request_id: str
    member: str
    zone: str
    requested_at: datetime
    candidates: list[tuple[ShadeKey, dict, float]]
    personalized: bool
    visible_count: int
    preferred: Shade
    intent: float


def mock_profile(rng, keys, catalog, day):
    preferred = catalog[keys[int(rng.integers(len(keys)))]]
    profile = Profile(preferred, float(rng.normal(0, 0.4)))
    if rng.random() < 0.76:
        probabilities = np.array([0.02 + style_match(preferred, catalog[key]) ** 3 for key in keys])
        for index in rng.choice(
            len(keys), size=1 + rng.poisson(5), p=probabilities / probabilities.sum()
        ):
            past_day = day - timedelta(days=int(rng.integers(1, 90)))
            profile.record(keys[index], past_day, 3.0 if rng.random() < 0.16 else 1.0)
    return profile


def draw_actions(rng, profile, shade, rating, rank, intent):
    affinity = style_match(profile.preferred, shade)
    appeal = 2.6 * affinity + 0.5 * (rating - 4.5) + rng.normal(0, 0.4)
    clicked = rng.random() < sigmoid(-1.6 + appeal + intent - 0.22 * (rank - 1))
    tried = clicked and rng.random() < sigmoid(-0.7 + 1.7 * affinity + 0.25 * intent)
    cart_logit = -1.75 + 1.65 * affinity + 0.75 * tried + 0.65 * intent
    cart = clicked and rng.random() < sigmoid(cart_logit)
    return int(clicked), int(tried), int(cart)


def generate_impressions(*, observe_request=None):
    rng = np.random.default_rng(SEED)
    catalogs, ratings = sampled_catalog(rng)
    keys = {zone: sorted(catalog) for zone, catalog in catalogs.items()}
    start = datetime(2026, 9, 1, tzinfo=UTC)
    profiles, rows = {}, []
    request = 0
    while len(rows) < IMPRESSION_COUNT:
        request += 1
        requested_at = start + timedelta(hours=3 * request)
        day = (requested_at + timedelta(hours=9)).date()
        member = f"mock-user-{int(rng.integers(MEMBER_COUNT)):03d}"
        request_id = f"mock-request-{request:04d}"
        zone = "lip" if rng.random() < 0.68 else "blush"
        catalog = catalogs[zone]
        if (member, zone) not in profiles:
            profiles[member, zone] = mock_profile(rng, keys[zone], catalog, day)
        profile = profiles[member, zone]
        daily = [
            (key, past_day, weight)
            for (key, past_day), weight in profile.daily.items()
            if 0 <= (day - past_day).days < 90
        ]
        candidates, personalized = score_inputs(zone, keys[zone], catalog, ratings[zone], daily)
        selected = top_chips(candidates, [row[2] for row in candidates], personalized)
        visible_count = min(
            int(rng.choice((1, 2, 3), p=(0.11, 0.19, 0.70))), IMPRESSION_COUNT - len(rows)
        )
        intent = profile.intent + rng.normal(0, 0.60)
        if observe_request is not None:
            observe_request(
                MockRequest(
                    request_id=request_id,
                    member=member,
                    zone=zone,
                    requested_at=requested_at,
                    candidates=candidates,
                    personalized=personalized,
                    visible_count=min(visible_count, len(selected)),
                    preferred=profile.preferred,
                    intent=float(intent),
                )
            )
        for rank, (key, features, _) in enumerate(selected[:visible_count], 1):
            clicked, tried, cart = draw_actions(
                rng, profile, catalog[key], features["rating_avg"], rank, intent
            )
            rows.append(
                {
                    "request_id": request_id,
                    "session_id": request_id,
                    "impression_id": f"{request_id}-{rank}",
                    "member": member,
                    "requested_at": requested_at.isoformat(),
                    "rank": rank,
                    "product_id": key[0],
                    "shade_id": key[1],
                    "strategy": "personalized" if personalized else "rating",
                    "features": features,
                    "clicked": clicked,
                    "tried_on": tried,
                    "added_to_cart": cart,
                }
            )
            if cart or tried:
                profile.record(key, day, 3.0 if cart else 0.7)
    return rows


def request_groups(rows):
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["request_id"]].append(index)
    return groups.values()


def comparison_pairs(rows):
    cart_pairs, ar_pairs = [], []
    for group in request_groups(rows):
        added = [i for i in group if rows[i]["added_to_cart"]]
        not_added = [i for i in group if not rows[i]["added_to_cart"]]
        tried_only = [i for i in not_added if rows[i]["tried_on"]]
        inactive = [i for i in not_added if not (rows[i]["clicked"] or rows[i]["tried_on"])]
        cart_pairs.extend(product(added, not_added))
        ar_pairs.extend(product(tried_only, inactive))
    return cart_pairs, ar_pairs


def ranking_metrics(rows, scores):
    scores = np.asarray(scores, dtype=float)
    if scores.shape != (len(rows),) or not np.isfinite(scores).all():
        raise ValueError("Expected one finite score per impression")
    ndcgs, hits = [], []
    for group in request_groups(rows):
        positive_count = sum(rows[i]["added_to_cart"] for i in group)
        if positive_count:
            ordered = sorted(group, key=lambda i: (-scores[i], rows[i]["rank"]))
            dcg = sum(
                rows[i]["added_to_cart"] * discount
                for i, discount in zip(ordered, DISCOUNTS, strict=False)
            )
            ndcgs.append(dcg / sum(DISCOUNTS[:positive_count]))
            hits.append(rows[ordered[0]]["added_to_cart"])

    cart_pairs, _ = comparison_pairs(rows)
    by_member = defaultdict(Counter)
    for first, second in cart_pairs:
        outcome = "win" if scores[first] > scores[second] else "loss"
        if scores[first] == scores[second]:
            outcome = "tie"
        by_member[rows[first]["member"]][outcome] += 1
    if not by_member:
        raise ValueError("Evaluation needs requests with both cart and non-cart impressions")

    def user_average(outcome):
        values = [counts[outcome] / sum(counts.values()) for counts in by_member.values()]
        return sum(values) / len(values)

    return {
        "ndcg_at_3": sum(ndcgs) / len(ndcgs),
        "user_auc": user_average("win"),
        "inversion_rate": user_average("loss"),
        "tie_rate": user_average("tie"),
        "hit_at_1": sum(hits) / len(hits),
        "positive_requests": len(ndcgs),
        "auc_users": len(by_member),
        "cart_pairs": len(cart_pairs),
    }


def bpr_features(training, evaluation):
    observations = training + evaluation
    columns = []
    for name in FEATURES:
        if name in CATEGORICAL:
            categories = sorted({features[name] for features in training})
            for category in categories:
                columns.append([features[name] == category for features in observations])
            continue
        values = np.asarray([features[name] for features in observations], dtype=float)
        known = values[: len(training)]
        known = known[np.isfinite(known)]
        mean = known.mean() if known.size else 0.0
        scale = (known.std() or 1.0) if known.size else 1.0
        missing = np.isnan(values)
        columns.extend((np.where(missing, 0.0, (values - mean) / scale), missing))
    matrix = np.array(columns, dtype=float).T
    return matrix[: len(training)], matrix[len(training) :]


def learn_bpr(train, evaluation, pairs, base_pair_count, parameters):
    train, evaluation = bpr_features(train, evaluation)
    positive, negative = np.asarray(pairs).T
    differences = train[positive] - train[negative]
    weights = np.zeros(train.shape[1])
    updates = base_pair_count * parameters["updates_per_pair"]
    learning_rate, l2 = parameters["learning_rate"], parameters["l2"]
    rng = np.random.default_rng(SEED)
    for index in rng.integers(len(pairs), size=updates):
        difference = differences[index]
        gradient = sigmoid(-float(weights @ difference)) * difference - l2 * weights
        weights += learning_rate * gradient
    return evaluation @ weights


def fit_and_score(name, train, evaluation, parameters, *, include_ar=False):
    eval_features = [row["features"] for row in evaluation]
    if name == "classifier":
        return score_model(fit_candidate(training_pool(train), parameters), eval_features)
    cart_pairs, ar_pairs = comparison_pairs(train)
    pairs = cart_pairs + ar_pairs if include_ar else cart_pairs
    train_features = [row["features"] for row in train]
    if name == "learnbpr":
        return learn_bpr(train_features, eval_features, pairs, len(cart_pairs), parameters)
    pool = Pool(
        feature_matrix(train_features),
        label=[row["added_to_cart"] for row in train],
        group_id=[row["request_id"] for row in train],
        pairs=pairs,
        feature_names=list(FEATURES),
        cat_features=list(CATEGORICAL),
        thread_count=FIXED_PARAMETERS["thread_count"],
    )
    fixed = {
        key: value
        for key, value in FIXED_PARAMETERS.items()
        if key not in {"loss_function", "auto_class_weights"}
    }
    model = CatBoostRanker(loss_function="PairLogit", **fixed, **parameters)
    model.fit(pool)
    return model.predict(feature_matrix(eval_features), thread_count=fixed["thread_count"])


def merit(metrics):
    return metrics["ndcg_at_3"], metrics["user_auc"]


def evaluate_models(train, validation, test):
    configurations = {
        "classifier": GRID_SPACE,
        "learnbpr": BPR_GRID,
        "pairlogit": GRID_SPACE,
    }
    models, test_scores = {}, {}
    for name, grid in configurations.items():
        print(f"Selecting {name} on validation", flush=True)
        trials = []
        for parameters in parameter_grid(grid):
            scores = fit_and_score(name, train, validation, parameters)
            metrics = ranking_metrics(validation, scores)
            trials.append({"parameters": parameters, "metrics": metrics})
        selected = max(trials, key=lambda trial: merit(trial["metrics"]))
        models[name] = {
            "parameters": selected["parameters"],
            "validation": selected["metrics"],
            "trials": trials,
        }

    chosen = max(("learnbpr", "pairlogit"), key=lambda name: merit(models[name]["validation"]))
    development = train + validation
    for name, result in models.items():
        scores = fit_and_score(name, development, test, result["parameters"])
        result["test"] = ranking_metrics(test, scores)
        test_scores[name] = list(map(float, scores))

    _, ar_pairs = comparison_pairs(development)
    ar_ablation = {"base": chosen, "additional_pairs": len(ar_pairs)}
    if ar_pairs:
        parameters = models[chosen]["parameters"]
        scores = fit_and_score(chosen, development, test, parameters, include_ar=True)
        ar_ablation["test"] = ranking_metrics(test, scores)
        test_scores["with_ar"] = list(map(float, scores))
    return models, ar_ablation, test_scores


def describe(rows):
    return {
        **summarize(rows),
        "requests": len({row["request_id"] for row in rows}),
        "clicks": sum(row["clicked"] for row in rows),
        "try_ons": sum(row["tried_on"] for row in rows),
        "rank_one_inactive": sum(row["rank"] == 1 and not row["clicked"] for row in rows),
        "lower_rank_carts": sum(row["rank"] > 1 and row["added_to_cart"] for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for dataset.json and results.json")
    output = parser.parse_args().output
    if output.exists():
        parser.error("choose a new output directory")

    rows = generate_impressions()
    train, validation, test, cutoffs = temporal_split(rows)
    splits = {
        name: describe(part)
        for name, part in (("train", train), ("validation", validation), ("test", test))
    }
    if any(not split["mixed_label_requests"] for split in splits.values()):
        raise ValueError("Each split needs at least one comparable cart request")
    summary = describe(rows)
    print(f"Generated {len(rows)} impressions across {summary['requests']} requests", flush=True)
    models, ar_ablation, scores = evaluate_models(train, validation, test)

    output.mkdir(parents=True)
    dataset = output / "dataset.json"
    write_json(
        dataset,
        {
            "source": "synthetic",
            "seed": SEED,
            "feature_version": FEATURE_VERSION,
            "catalog_path": CATALOG.relative_to(ROOT).as_posix(),
            "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
            "catalog_products_by_zone": ZONE_COUNTS,
            "user_history_source": "regenerated from the documented v1.1 mock setup",
            "rule": "app.core.ar_palette.score_inputs and top_chips",
            "rows": rows,
        },
    )
    results = {
        "seed": SEED,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "versions": {"catboost": catboost.__version__, "numpy": np.__version__},
        "summary": summary,
        "cutoffs": cutoffs,
        "splits": splits,
        "training_cart_pairs": len(comparison_pairs(train)[0]),
        "development_cart_pairs": len(comparison_pairs(train + validation)[0]),
        "models": models,
        "ar_ablation": ar_ablation,
        "test_impression_ids": [row["impression_id"] for row in test],
        "test_scores": scores,
    }
    write_json(output / "results.json", results)
    for name, result in models.items():
        print(name, result["test"])
    print("AR ablation", ar_ablation)


if __name__ == "__main__":
    main()
