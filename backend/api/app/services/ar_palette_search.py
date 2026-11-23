"""Training-only hyperparameter comparison for the AR palette ranker."""

from itertools import groupby, product
from random import Random

from app.core.ar_palette import CATEGORICAL, FEATURES
from app.core.ar_palette_artifacts import CLASSIFIER, RANKER, feature_matrix

SEARCH_METHODS = ("grid", "random", "optuna")
SEED = 42
SEARCH_SPACE = {
    "iterations": (120, 180, 260, 360),
    "depth": (3, 4, 5, 6),
    "learning_rate": (0.03, 0.05, 0.08, 0.12),
    "l2_leaf_reg": (1.0, 3.0, 7.0, 12.0),
}
GRID_SPACE = {
    "iterations": (180, 360),
    "depth": (4, 6),
    "learning_rate": (0.03, 0.08),
    "l2_leaf_reg": (3.0, 12.0),
}
COMMON_PARAMETERS = {
    "random_seed": SEED,
    "thread_count": 2,
    "allow_writing_files": False,
    "verbose": False,
}
FIXED_PARAMETERS = {
    **COMMON_PARAMETERS,
    "loss_function": "Logloss",
    "auto_class_weights": "Balanced",
}
MODEL_PARAMETERS = {
    CLASSIFIER: FIXED_PARAMETERS,
    RANKER: {**COMMON_PARAMETERS, "loss_function": "PairLogit"},
}


def parameter_grid(space):
    return [dict(zip(space, values, strict=True)) for values in product(*space.values())]


def training_pool(rows, *, model_type=CLASSIFIER):
    from catboost import Pool

    ranking = {}
    if model_type == RANKER:
        slots = {}
        for row in rows:
            key = (row["request_id"], row["rank"])
            if key not in slots or row["added_to_cart"] > slots[key]["added_to_cart"]:
                slots[key] = row
        rows = [slots[key] for key in sorted(slots)]
        pairs = []
        for _, group in groupby(enumerate(rows), key=lambda entry: entry[1]["request_id"]):
            added, not_added = [], []
            for index, row in group:
                (added if row["added_to_cart"] else not_added).append(index)
            pairs.extend(product(added, not_added))
        ranking = {"group_id": [row["request_id"] for row in rows], "pairs": pairs}

    return Pool(
        feature_matrix([row["features"] for row in rows]),
        label=[row["added_to_cart"] for row in rows],
        feature_names=list(FEATURES),
        cat_features=list(CATEGORICAL),
        thread_count=FIXED_PARAMETERS["thread_count"],
        **ranking,
    )


def fit_candidate(pool, parameters, *, model_type=CLASSIFIER):
    from catboost import CatBoostClassifier, CatBoostRanker

    model_class = CatBoostRanker if model_type == RANKER else CatBoostClassifier
    model = model_class(**MODEL_PARAMETERS[model_type], **parameters)
    model.fit(pool)
    return model


def optuna_trials(evaluate, all_parameters, budget, metric_key):
    from optuna import create_study
    from optuna.samplers import TPESampler
    from optuna.trial import TrialState

    study = create_study(direction="maximize", sampler=TPESampler(seed=SEED, n_startup_trials=4))
    seen = set()
    reserve = iter(Random(SEED).sample(all_parameters, len(all_parameters)))
    trials = []

    def suggest(trial):
        return {
            name: trial.suggest_categorical(name, choices) for name, choices in SEARCH_SPACE.items()
        }

    for _ in range(budget):
        trial = study.ask()
        parameters = suggest(trial)
        if tuple(parameters.values()) in seen:
            study.tell(trial, state=TrialState.PRUNED)
            unseen = next(item for item in reserve if tuple(item.values()) not in seen)
            study.enqueue_trial(unseen)
            trial = study.ask()
            parameters = suggest(trial)
        seen.add(tuple(parameters.values()))
        score = evaluate(parameters)
        study.tell(trial, score)
        trials.append({"parameters": parameters, metric_key: score})
    return trials


def compare_searches(evaluate, method, *, metric="hit_at_1"):
    grid = parameter_grid(GRID_SPACE)
    all_parameters = parameter_grid(SEARCH_SPACE)
    budget = len(grid)
    metric_key = f"validation_{metric}"
    methods = SEARCH_METHODS if method == "compare" else (method,)
    results = {}

    def merit(trial):
        parameters = trial["parameters"]
        return (trial[metric_key], -parameters["iterations"], -parameters["depth"])

    for choice in methods:
        if choice == "optuna":
            trials = optuna_trials(evaluate, all_parameters, budget, metric_key)
        else:
            samples = grid if choice == "grid" else Random(SEED).sample(all_parameters, budget)
            trials = [{"parameters": params, metric_key: evaluate(params)} for params in samples]
        results[choice] = {"best": max(trials, key=merit), "trials": trials}
    selected = max(results, key=lambda choice: merit(results[choice]["best"]))
    return {
        "method": selected,
        "requested_method": method,
        "trials_per_method": budget,
        "objective": f"mixed_label_request_{metric}",
        "search_space": SEARCH_SPACE,
        "grid_space": GRID_SPACE,
        f"best_{metric_key}": results[selected]["best"][metric_key],
        "parameters": results[selected]["best"]["parameters"],
        "results": results,
    }
