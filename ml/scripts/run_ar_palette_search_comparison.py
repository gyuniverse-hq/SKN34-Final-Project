"""Compare saved grid results with RandomSearch and Optuna on the same holdout."""

import argparse
from pathlib import Path
from random import Random

import optuna
from ml.scripts import run_ar_palette_bpr as study
from ml.scripts import run_ar_palette_bpr_mf as mf
from optuna.samplers import TPESampler
from optuna.trial import TrialState

TRIALS = 16
OPTUNA_STARTUP_TRIALS = 4
LEARNING_RATES = (0.01, 0.02, 0.03, 0.04)
REGULARIZATION = (0.001, 0.005, 0.01, 0.025, 0.05)
LINEAR_SPACE = {
    "learning_rate": LEARNING_RATES,
    "l2": REGULARIZATION,
    "updates_per_pair": study.BPR_GRID["updates_per_pair"],
}
MF_SPACE = {
    "factors": (8, 12, 16),
    "learning_rate": LEARNING_RATES,
    "l2": REGULARIZATION,
    "updates_per_pair": (30, 40, 50, 60),
}


def model_parameters(name, candidate):
    if name != "bpr_mf":
        return candidate
    parameters = candidate.copy()
    l2 = parameters.pop("l2")
    parameters["regularization"] = {"user": l2, "positive": l2, "negative": l2 / 10}
    return parameters


def optuna_trials(space, candidates, evaluate, seed):
    tuner = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=seed, n_startup_trials=OPTUNA_STARTUP_TRIALS),
    )
    reserve = iter(Random(seed).sample(candidates, len(candidates)))
    seen, trials = set(), []
    replacements = 0

    def suggest(trial):
        return {key: trial.suggest_categorical(key, choices) for key, choices in space.items()}

    for _ in range(TRIALS):
        trial = tuner.ask()
        candidate = suggest(trial)
        if tuple(candidate.values()) in seen:
            tuner.tell(trial, state=TrialState.PRUNED)
            unseen = next(value for value in reserve if tuple(value.values()) not in seen)
            tuner.enqueue_trial(unseen)
            trial = tuner.ask()
            candidate = suggest(trial)
            replacements += 1
        seen.add(tuple(candidate.values()))
        record = evaluate(candidate)
        tuner.tell(trial, record["metrics"]["ndcg_at_3"])
        trials.append(record)
    return trials, replacements


def predictions(name, train, evaluation, parameters, seed):
    if name == "bpr_mf":
        indexed = mf.index_triplets(train)
        factors = mf.fit_bpr_mf(indexed, parameters, seed)
        return mf.predict(indexed, factors, evaluation)
    return study.fit_and_score(name, train, evaluation, parameters)


def tune_model(name, space, train, validation, seed):
    candidates = study.parameter_grid(space)

    def evaluate(candidate):
        parameters = model_parameters(name, candidate)
        scores = predictions(name, train, validation, parameters, seed)
        return {"parameters": parameters, "metrics": study.ranking_metrics(validation, scores)}

    print(f"{name}: RandomSearch ({TRIALS} trials)", flush=True)
    random_trials = [evaluate(candidate) for candidate in Random(seed).sample(candidates, TRIALS)]
    print(f"{name}: Optuna ({TRIALS} trials)", flush=True)
    tpe_trials, replacements = optuna_trials(space, candidates, evaluate, seed)

    results = {}
    for method, trials in (("random", random_trials), ("optuna", tpe_trials)):
        selected = max(trials, key=lambda trial: study.merit(trial["metrics"]))
        results[method] = {
            "parameters": selected["parameters"],
            "validation": selected["metrics"],
            "trials": trials,
        }
    results["optuna"]["duplicate_replacements"] = replacements
    return results


def saved_grid_results(baseline, mf_run, test):
    fields = ("dataset_sha256", "cutoffs", "test_impression_ids", "seed")
    if any(baseline[field] != mf_run[field] for field in fields):
        raise ValueError("The saved grid runs use different datasets, time splits or seeds")

    grids = {}
    for name in mf.BASE_MODELS:
        model = baseline["models"][name]
        grids[name] = {
            "parameters": model["parameters"],
            "validation": model["validation"],
            "test": model["test"],
            "trials": model["trials"],
            "test_scores": baseline["test_scores"][name],
        }
    grids["bpr_mf"] = {
        "parameters": mf_run["selected"]["parameters"],
        "validation": mf_run["selected"]["metrics"],
        "test": mf_run["test_comparison"]["bpr_mf"],
        "trials": mf_run["validation_trials"],
        "test_scores": mf_run["test_scores_bpr_mf"],
    }
    for name, grid in grids.items():
        if len(grid["trials"]) != TRIALS:
            raise ValueError(f"The saved grid budget differs for {name}")
        if study.ranking_metrics(test, grid["test_scores"]) != grid["test"]:
            raise ValueError(f"The saved grid scores differ for {name}")
    return grids


def main():
    from app.services.ar_palette_search import SEARCH_SPACE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_run", type=Path, help="Original three-model grid run")
    parser.add_argument("mf_run", type=Path, help="BPR-MF grid run")
    parser.add_argument("output", type=Path, help="New output directory for results.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output directory")
    baseline, train, validation, test = mf.load_holdout(args.base_run)
    grids = saved_grid_results(baseline, study.read_json(args.mf_run / "results.json"), test)
    seed = baseline["seed"]
    spaces = {
        "classifier": SEARCH_SPACE,
        "learnbpr": LINEAR_SPACE,
        "pairlogit": SEARCH_SPACE,
        "bpr_mf": MF_SPACE,
    }
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    results = {
        name: {"grid": grids[name], **tune_model(name, space, train, validation, seed)}
        for name, space in spaces.items()
    }
    development = train + validation
    for name, methods in results.items():
        for method in ("random", "optuna"):
            result = methods[method]
            scores = predictions(name, development, test, result["parameters"], seed)
            result["test"] = study.ranking_metrics(test, scores)
            result["test_scores"] = list(map(float, scores))

    args.output.mkdir(parents=True)
    study.write_json(
        args.output / "results.json",
        {
            "grid_runs": [args.base_run.as_posix(), args.mf_run.as_posix()],
            "dataset_sha256": baseline["dataset_sha256"],
            "splits": baseline["splits"],
            "cutoffs": baseline["cutoffs"],
            "test_impression_ids": baseline["test_impression_ids"],
            "seed": seed,
            "versions": {**baseline["versions"], "optuna": optuna.__version__},
            "trials_per_method": TRIALS,
            "optuna_startup_trials": OPTUNA_STARTUP_TRIALS,
            "search_spaces": spaces,
            "models": results,
        },
    )
    for name, methods in results.items():
        line = [
            f"{method}={result['test']['ndcg_at_3']:.4f}/{result['test']['user_auc']:.4f}"
            for method, result in methods.items()
        ]
        print(name, " ".join(line))


if __name__ == "__main__":
    main()
