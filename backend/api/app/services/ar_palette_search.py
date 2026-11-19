"""Training-only hyperparameter comparison for the AR palette ranker."""

from itertools import product
from random import Random

from app.core.ar_palette import CATEGORICAL, FEATURES
from app.core.ar_palette_artifacts import feature_matrix

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
FIXED_PARAMETERS = {
    "auto_class_weights": "Balanced",
    "random_seed": SEED,
    "loss_function": "Logloss",
    "thread_count": 2,
    "allow_writing_files": False,
    "verbose": False,
}


def parameter_grid(space):
    return [dict(zip(space, values, strict=True)) for values in product(*space.values())]


def training_pool(rows):
    from catboost import Pool

    return Pool(
        feature_matrix([row["features"] for row in rows]),
        label=[row["added_to_cart"] for row in rows],
        feature_names=list(FEATURES),
        cat_features=list(CATEGORICAL),
        thread_count=FIXED_PARAMETERS["thread_count"],
    )


def fit_candidate(pool, parameters):
    from catboost import CatBoostClassifier

    model = CatBoostClassifier(**FIXED_PARAMETERS, **parameters)
    model.fit(pool)
    return model


def optuna_trials(evaluate, all_parameters, budget):
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
        trials.append({"parameters": parameters, "validation_hit_at_1": score})
    return trials


def compare_searches(evaluate, method):
    grid = parameter_grid(GRID_SPACE)
    all_parameters = parameter_grid(SEARCH_SPACE)
    budget = len(grid)
    methods = SEARCH_METHODS if method == "compare" else (method,)
    results = {}

    def merit(trial):
        parameters = trial["parameters"]
        return (trial["validation_hit_at_1"], -parameters["iterations"], -parameters["depth"])

    for choice in methods:
        if choice == "optuna":
            trials = optuna_trials(evaluate, all_parameters, budget)
        else:
            samples = grid if choice == "grid" else Random(SEED).sample(all_parameters, budget)
            trials = [
                {"parameters": params, "validation_hit_at_1": evaluate(params)}
                for params in samples
            ]
        results[choice] = {"best": max(trials, key=merit), "trials": trials}
    selected = max(results, key=lambda choice: merit(results[choice]["best"]))
    return {
        "method": selected,
        "requested_method": method,
        "trials_per_method": budget,
        "objective": "mixed_label_request_hit_at_1",
        "search_space": SEARCH_SPACE,
        "grid_space": GRID_SPACE,
        "best_validation_hit_at_1": results[selected]["best"]["validation_hit_at_1"],
        "parameters": results[selected]["best"]["parameters"],
        "results": results,
    }
