"""Sequential, resumable A→B→C→D study with locked test access and Korean reports.

Run from repository root:
uv run --project ml python -m skin_analysis.smartphone.reselection init
uv run --project ml python -m skin_analysis.smartphone.reselection run
"""

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from server.nia.metrics import classification

from ..config import PROJECT_ROOT
from ..runtime import select_cuda
from .common import PREPROCESSING, TASKS, digest, file_hash, load_manifest
from .data import GradeDataset
from .sam import optimization_spec
from .study_design import (
    atomic_json,
    backbone_recipes,
    factorial_recipes,
    loss_recipes,
    optimizer_recipe,
    paired_bootstrap,
    prediction_cube,
    read_json,
    recipe_id,
    split_manifest,
)
from .train import GradeModel, make_loader, predict, train_task, verify_crops

DEFAULT_STUDY = PROJECT_ROOT / "configs/nia_smartphone_reselection.toml"
STAGES = ("A", "B", "C", "D", "delivery")


def timestamp():
    return datetime.now(UTC).isoformat()


def source_fingerprint():
    repo = PROJECT_ROOT.parent
    paths = sorted((PROJECT_ROOT / "src").rglob("*.py")) + [repo / "server/nia/metrics.py"]
    return digest({p.relative_to(repo).as_posix(): file_hash(p) for p in paths})


def load_study(path):
    config = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    settings = config["study"]
    for key in ("output", "reports", "data_output"):
        settings[key] = str((PROJECT_ROOT / settings[key]).resolve())
    if (
        settings["protocol"] != "reselection-v1"
        or settings["tasks"] != list(TASKS)
        or settings["search_seeds"] != [17, 42, 73]
        or settings["confirmation_seeds"] != [17, 42, 73, 101, 202]
        or (config["train"]["freeze_epochs"], config["train"]["finetune_epochs"]) != (2, 18)
        or not config["train"]["fixed_epochs"]
        or config["train"]["selection"] != "macro_f1_mae"
    ):
        raise ValueError("This runner implements only the preregistered reselection-v1 protocol")
    return config


def original_manifest(config):
    manifest = load_manifest(dict(data=dict(output=config["study"]["data_output"])))
    if manifest["fingerprint"] != config["study"]["data_fingerprint"]:
        raise ValueError("Preregistered source fingerprint differs")
    return manifest


def make_run(config, task, recipe, seed, *, fold=None, delivery=False):
    identity = dict(task=task, recipe=recipe, seed=seed, fold=fold, delivery=delivery)
    identifier = digest(identity)[:20]
    return dict(
        id=identifier,
        task=task,
        recipe=recipe,
        seed=seed,
        fold=fold,
        delivery=delivery,
        status="planned",
        attempts=[],
    )


def register(state, stage, entry):
    state["runs"].setdefault(entry["id"], entry)
    if entry["id"] not in state["stages"][stage]["runs"]:
        state["stages"][stage]["runs"].append(entry["id"])


def stage_groups(state, stages, *, task=None):
    groups = defaultdict(list)
    ids = set()
    for stage in stages:
        ids.update(state["stages"][stage]["runs"])
    for identifier in sorted(ids):
        run = state["runs"][identifier]
        if run["status"] == "completed" and (task is None or task == run["task"]):
            groups[(run["task"], recipe_id(run["recipe"]))].append(run)
    return groups


def ranked(state, stages, task, predicate=lambda r: True):
    rows = []
    for (_, identifier), runs in stage_groups(state, stages, task=task).items():
        recipe = runs[0]["recipe"]
        if not predicate(recipe):
            continue
        if {run["seed"] for run in runs} != set(state["config"]["study"]["search_seeds"]):
            raise ValueError("Do not rank incomplete seed groups")
        score = np.mean([r["result"]["metrics"]["overall"]["macro_f1"] for r in runs])
        rows.append((float(score), identifier, recipe))
    return sorted(rows, key=lambda row: (-row[0], row[1]))


def initialize(config):
    root = Path(config["study"]["output"])
    state_path = root / "study.json"
    if state_path.exists():
        state = read_json(state_path)
        if state["config"] != config or state["source_hash"] != source_fingerprint():
            raise ValueError("Existing study has a different config/source; use a new output")
        return state
    manifest = original_manifest(config)
    verify_crops(manifest)
    root.mkdir(parents=True, exist_ok=True)
    state = dict(
        schema="skin-reselection-v1",
        created=timestamp(),
        updated=timestamp(),
        config=config,
        config_hash=digest(config),
        source_hash=source_fingerprint(),
        data_fingerprint=manifest["fingerprint"],
        source_summary=manifest["summary"],
        stages={key: dict(status="planned", runs=[]) for key in STAGES},
        runs={},
        aliases={},
        selections={},
        audit_status="locked",
        status="planned",
    )
    state["code_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    state["working_tree_dirty"] = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT.parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    for task in TASKS:
        for row in factorial_recipes(manifest["records"], task, config["study"]["batch_sizes"]):
            key = f"{task}:{recipe_id(row['recipe'])}"
            state["aliases"][key] = dict(aliases=row["aliases"], weights=row["weights"])
            for seed in config["study"]["search_seeds"]:
                register(state, "A", make_run(config, task, row["recipe"], seed))
    # Freeze all development folds before looking at any new training results.
    state["folds"] = []
    for fold in range(config["study"]["outer_folds"]):
        divided = split_manifest(
            manifest,
            fold,
            split_seed=config["study"]["split_seed"],
            outer_folds=config["study"]["outer_folds"],
            inner_folds=config["study"]["inner_folds"],
        )
        destination = root / "folds" / str(fold) / "manifest.json"
        atomic_json(destination, divided)
        state["folds"].append(dict(fingerprint=divided["fingerprint"], summary=divided["summary"]))
    # Preserve the actual historical documents byte for byte, once only.
    reports = Path(config["study"]["reports"])
    for name in ("final-model-report", "experiment-summary"):
        source, backup = reports / f"{name}.md", reports / f"{name}.previous.md"
        if source.exists() and not backup.exists():
            shutil.copy2(source, backup)
    atomic_json(root / "protocol.json", dict(config=config, source_hash=state["source_hash"]))
    save_state(state)
    return state


def save_state(state):
    from .study_report import publish_study

    state["updated"] = timestamp()
    atomic_json(Path(state["config"]["study"]["output"]) / "study.json", state)
    publish_study(state)


def prepare_stage(state, stage):
    settings = state["config"]["study"]
    if state["stages"][stage]["runs"]:
        return
    config = state["config"]
    for task in TASKS:
        if stage == "B":
            reference = ranked(state, ["A"], task, lambda r: r["loss"] == "weighted_cross_entropy")[
                0
            ][2]
            state["stages"][stage].setdefault("references", {})[task] = reference
            recipes = list(loss_recipes(reference)) + [
                optimizer_recipe(reference, optimizer) for optimizer in ("adamw", "sam_adamw")
            ]
        elif stage == "C":
            reference = ranked(state, ["A", "B"], task, lambda r: r["loss"] != "coral")[0][2]
            state["stages"][stage].setdefault("references", {})[task] = reference
            recipes = list(
                backbone_recipes(reference, settings["backbones"], settings["lr_multipliers"])
            )
        elif stage == "D":
            candidates = [row[2] for row in ranked(state, ["A", "B", "C"], task)[:2]]
            baseline = ranked(
                state,
                ["A"],
                task,
                lambda r: r["loss"] == "unweighted_cross_entropy" and r["optimizer"] == "adamw",
            )[0][2]
            unique = {recipe_id(r): r for r in [*candidates, baseline]}
            state["stages"][stage].setdefault("candidates", {})[task] = list(unique)
            for recipe in unique.values():
                for fold in range(settings["outer_folds"]):
                    for seed in settings["confirmation_seeds"]:
                        register(state, stage, make_run(config, task, recipe, seed, fold=fold))
            continue
        elif stage == "delivery":
            recipe = state["selections"][task]["recipe"]
            register(state, stage, make_run(config, task, recipe, 42, delivery=True))
            continue
        else:
            raise ValueError("Unknown dependent stage")
        for recipe in recipes:
            for seed in settings["search_seeds"]:
                register(state, stage, make_run(config, task, recipe, seed))
    state["stages"][stage]["prepared"] = timestamp()
    save_state(state)


def configure_attempt(state, run, attempt_root):
    root = Path(state["config"]["study"]["output"])
    settings = copy.deepcopy(state["config"]["train"])
    recipe = dict(run["recipe"])
    multiplier = recipe.pop("lr_multiplier")
    settings.update(recipe)
    settings.update(
        seed=run["seed"],
        output=str(attempt_root),
        effective_batch=recipe["batch_size"],
        expected_source_hash=state["source_hash"],
    )
    for name in ("head_lr", "finetune_head_lr", "backbone_lr"):
        settings[name] *= multiplier
    data_output = (
        state["config"]["study"]["data_output"]
        if run["fold"] is None
        else str(root / "folds" / str(run["fold"]))
    )
    return dict(data=dict(output=data_output), train=settings)


def execute_run(state, run, *, persist=None, timeout_seconds=None):
    persist = save_state if persist is None else persist
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    if run["status"] == "completed":
        # A reported completion never silently substitutes a missing artifact.
        artifact = Path(run["result"]["checkpoint"])
        if not artifact.is_file() or file_hash(artifact) != run["result"]["sha256"]:
            raise ValueError("Completed run checkpoint missing or changed")
        return
    root = Path(state["config"]["study"]["output"])
    max_attempts = state["config"]["study"]["max_attempts"]
    # Interrupted attempts resume from last.pt; invalid attempts stay immutable.
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("Study training deadline reached")
        if run["attempts"] and run["attempts"][-1]["status"] == "running":
            attempt = run["attempts"][-1]
        else:
            if len(run["attempts"]) >= max_attempts:
                raise RuntimeError(f"Run {run['id']} exhausted attempts; inspect private log")
            attempt = dict(number=len(run["attempts"]) + 1, status="running", started=timestamp())
            run["attempts"].append(attempt)
        attempt_root = root / "runs" / run["id"] / f"attempt-{attempt['number']}"
        attempt_root.mkdir(parents=True, exist_ok=True)
        config_path = attempt_root / "config.json"
        if not config_path.exists():
            atomic_json(config_path, configure_attempt(state, run, attempt_root))
        run["status"] = "running"
        state["active_run"] = run["id"]
        persist(state)
        started = time.perf_counter()
        command = [
            sys.executable,
            "-m",
            "skin_analysis.smartphone.reselection",
            "worker",
            "--attempt",
            str(attempt_root),
            "--task",
            run["task"],
        ]
        if run["fold"] is not None:
            command.append("--outer")
        with (attempt_root / "worker.log").open("a", encoding="utf-8") as log:
            with subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT.parent
            ) as process:
                try:
                    returncode = process.wait(timeout=remaining)
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                    # Kill the owned launcher AND its Python/DataLoader children on Windows.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    process.wait()
                    attempt["elapsed_seconds"] = (
                        attempt.get("elapsed_seconds", 0) + time.perf_counter() - started
                    )
                    attempt["paused_at"] = timestamp()
                    run["status"] = "interrupted"
                    persist(state)
                    if isinstance(error, KeyboardInterrupt):
                        raise
                    raise TimeoutError("Study training deadline reached") from error
        attempt["elapsed_seconds"] = (
            attempt.get("elapsed_seconds", 0) + time.perf_counter() - started
        )
        attempt["finished"] = timestamp()
        result_path = attempt_root / "result.json"
        if returncode == 0 and result_path.exists():
            attempt["status"] = run["status"] = "completed"
            run["result"] = read_json(result_path)
            run["result"]["execution_wall_seconds"] = attempt["elapsed_seconds"]
            run["result"]["attempt_root"] = str(attempt_root)
            persist(state)
            return
        attempt["status"] = run["status"] = "invalid"
        attempt["exit_code"] = returncode
        if (attempt_root / "failure.json").exists():
            failure = read_json(attempt_root / "failure.json")
            attempt["error_type"] = failure["error_type"]
            attempt["error_summary"] = failure["error_summary"]
        persist(state)


def add_sensitivity(state):
    stage = state["stages"]["C"]
    if "sensitivity_runs" not in stage:
        stage["sensitivity_runs"] = []
        for task in TASKS:
            recipe = ranked(state, ["C"], task, lambda r: r["optimizer"] == "sam_adamw")[0][2]
            for rho in state["config"]["study"]["rho_values"]:
                for seed in state["config"]["study"]["search_seeds"]:
                    run = make_run(state["config"], task, recipe | dict(sam_rho=rho), seed)
                    state["runs"].setdefault(run["id"], run)
                    stage["sensitivity_runs"].append(run["id"])
        save_state(state)


def oof_predictions(state, task, identifier):
    predictions = defaultdict(list)
    for run_id in state["stages"]["D"]["runs"]:
        run = state["runs"][run_id]
        if run["task"] == task and recipe_id(run["recipe"]) == identifier:
            if run["status"] != "completed":
                raise ValueError("Confirmation incomplete")
            rows = read_json(Path(run["result"]["attempt_root"]) / "predictions.json")
            predictions[run["seed"]].extend(rows)
    return dict(predictions)


def choose_models(state):
    settings = state["config"]["study"]
    for task, candidate_ids in state["stages"]["D"]["candidates"].items():
        candidates = []
        alignment = None
        for identifier in candidate_ids:
            predictions = oof_predictions(state, task, identifier)
            cube, current = prediction_cube(predictions, TASKS[task]["classes"])
            if alignment is not None and alignment != current:
                raise ValueError("Candidates have different OOF subjects, truth or seeds")
            alignment = current
            seed_metrics = [
                classification(
                    [r["truth"] for r in rows],
                    [r["predicted"] for r in rows],
                    TASKS[task]["classes"],
                )
                for _, rows in sorted(predictions.items())
            ]
            runs = [
                state["runs"][r]
                for r in state["stages"]["D"]["runs"]
                if state["runs"][r]["task"] == task
                and recipe_id(state["runs"][r]["recipe"]) == identifier
            ]
            candidates.append(
                dict(
                    id=identifier,
                    recipe=runs[0]["recipe"],
                    cube=cube,
                    mean_macro_f1=float(np.mean([m["macro_f1"] for m in seed_metrics])),
                    std_macro_f1=float(np.std([m["macro_f1"] for m in seed_metrics], ddof=1)),
                    seed_metrics=seed_metrics,
                    latency_ms=float(np.median([r["result"]["latency_ms"] for r in runs])),
                    parameter_count=runs[0]["result"]["parameter_count"],
                )
            )
        best = max(candidates, key=lambda c: (c["mean_macro_f1"], c["id"]))
        eligible = []
        for candidate in candidates:
            interval = paired_bootstrap(
                candidate["cube"],
                best["cube"],
                samples=settings["bootstrap_samples"],
                seed=settings["bootstrap_seed"],
            )
            candidate["difference_vs_best"] = interval
            if candidate is best or interval["lower"] <= 0 <= interval["upper"]:
                eligible.append(candidate)
        chosen = min(
            eligible,
            key=lambda c: (
                c["latency_ms"],
                c["parameter_count"],
                c["recipe"]["optimizer"] != "adamw",
                c["recipe"]["loss"] != "unweighted_cross_entropy",
                c["id"],
            ),
        )
        state["selections"][task] = dict(
            recipe=chosen["recipe"],
            candidate_id=chosen["id"],
            highest_mean_id=best["id"],
            reason="mean OOF Macro-F1; paired-interval ties resolved by latency/size/SAM/CE",
            candidates=[{k: v for k, v in c.items() if k != "cube"} for c in candidates],
            selected_at=timestamp(),
        )
    state["selection_hash"] = digest(state["selections"])
    save_state(state)


def evaluate_checkpoint(checkpoint_path, manifest, task, split, device):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if (
        checkpoint["task"] != task
        or checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["preprocessing"] != PREPROCESSING
        or checkpoint["grades"] != list(range(TASKS[task]["classes"]))
    ):
        raise ValueError("Evaluation checkpoint/data/grade contract differs")
    ordinal = checkpoint["architecture"] == "resnet50_coral"
    backbone = "resnet50" if ordinal else checkpoint["architecture"]
    model = GradeModel(TASKS[task]["classes"], ordinal=ordinal, backbone=backbone).to(device)
    model.network.load_state_dict(checkpoint["model_state"], strict=True)
    data = GradeDataset(manifest, task, split)
    loader = make_loader(data, dict(batch_size=32, num_workers=0))
    truth, predicted, _, loss = predict(model, loader, device, ordinal=ordinal)
    from .evaluate import metrics_for

    metrics = metrics_for(data.records, truth, predicted, TASKS[task]["classes"])
    for subset, indices in [
        (metrics["overall"], list(range(len(data.records)))),
        *[
            (m, [i for i, r in enumerate(data.records) if r["area"] == area])
            for area, m in metrics["areas"].items()
        ],
    ]:
        selected_indices = indices
        rows = [data.records[i] for i in indices]
        high = TASKS[task]["classes"] - 2
        positive = [i for i in selected_indices if truth[i] >= high]
        detected = [i for i in selected_indices if predicted[i] >= high]
        true_positive = sum(predicted[i] >= high for i in positive)
        subset.update(
            subjects=len({r["subject"] for r in rows}),
            grade_subject_support=[
                len({r["subject"] for r in rows if r["truth"] == grade})
                for grade in range(TASKS[task]["classes"])
            ],
            high_grade_exact_recall=(
                sum(truth[i] == predicted[i] for i in positive) / len(positive) if positive else 0.0
            ),
            high_grade_detection_recall=true_positive / len(positive) if positive else 0.0,
            high_grade_detection_precision=true_positive / len(detected) if detected else 0.0,
        )
    rows = [
        dict(id=r["id"], group=r["group"], truth=t, predicted=p)
        for r, t, p in zip(data.records, truth, predicted, strict=True)
    ]
    # Hardware cost uses warm-up then synchronized forward-only batch1 FP32.
    model.eval()
    image = data[0][0].unsqueeze(0).to(device)
    durations = []
    with torch.inference_mode():
        for index in range(60):
            torch.cuda.synchronize(device)
            started = time.perf_counter()
            model(image)
            torch.cuda.synchronize(device)
            if index >= 10:
                durations.append((time.perf_counter() - started) * 1000)
    return dict(
        metrics=metrics,
        evaluation_loss=loss,
        latency_ms=float(np.median(durations)),
        architecture=checkpoint["architecture"],
        decoding=checkpoint["decoding"],
        initialization=checkpoint["initialization"],
        preprocessing=checkpoint["preprocessing"],
        loss_spec=checkpoint["loss_spec"],
        environment=checkpoint["environment"],
    ), rows


def worker(attempt_root, task, outer):
    config = read_json(attempt_root / "config.json")
    if config["train"]["expected_source_hash"] != source_fingerprint():
        raise ValueError("Source changed after preregistration")
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    # Keep both optimizers' FP32 evaluation/AMP training policies explicit.
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    manifest = load_manifest(config)
    if outer and "study_fold" not in manifest:
        raise ValueError("Outer evaluation cannot read the original test manifest")
    verify_crops(manifest)
    inference = attempt_root / task / "inference.bin"
    started = time.perf_counter()
    if not inference.exists():
        resume = attempt_root / task / "last.pt"
        train_task(config, manifest, task, device, resume=resume if resume.exists() else None)
    summary = read_json(attempt_root / task / "summary.json")
    if summary["epochs_run"] != 20:
        raise ValueError("Study requires all 20 epochs, not an early-stopped checkpoint")
    if summary["sha256"] != file_hash(inference):
        raise ValueError("Inference checkpoint changed after export")
    evaluated, predictions = evaluate_checkpoint(
        inference, manifest, task, "test" if outer else "valid", device
    )
    atomic_json(attempt_root / "predictions.json", predictions)
    if config["train"]["expected_source_hash"] != source_fingerprint():
        raise ValueError("Source changed while training; invalidate this attempt")
    result = (
        summary
        | evaluated
        | dict(
            checkpoint=str(inference),
            task=task,
            fold=manifest.get("study_fold"),
            source_hash=source_fingerprint(),
            data_fingerprint=manifest["fingerprint"],
            config_hash=digest(config),
            worker_wall_seconds=time.perf_counter() - started,
            split="outer_evaluation" if outer else "valid",
            optimization=optimization_spec(config["train"]),
        )
    )
    atomic_json(attempt_root / "result.json", result)


def audit(state):
    if state["selection_hash"] != digest(state["selections"]):
        raise ValueError("Selection changed before test audit")
    config = state["config"]
    root = Path(config["study"]["output"])
    if (root / "test-audit.json").exists():
        state["audit"] = read_json(root / "test-audit.json")
        if state["audit"]["selection_hash"] != state["selection_hash"]:
            raise ValueError("Existing audit is for another selection")
        state["audit_status"] = "completed"
        return
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    manifest = original_manifest(config)
    verify_crops(manifest)
    results = {}
    for task in TASKS:
        final_run = next(
            state["runs"][r]
            for r in state["stages"]["delivery"]["runs"]
            if state["runs"][r]["task"] == task
        )
        baseline_recipe = ranked(
            state,
            ["A"],
            task,
            lambda r: r["loss"] == "unweighted_cross_entropy" and r["optimizer"] == "adamw",
        )[0][2]
        baseline_run = next(
            r
            for r in state["runs"].values()
            if r["task"] == task
            and r["recipe"] == baseline_recipe
            and r["seed"] == 42
            and r["fold"] is None
            and not r["delivery"]
        )
        results[task] = {}
        for name, run in (("selected", final_run), ("ce_baseline", baseline_run)):
            if file_hash(run["result"]["checkpoint"]) != run["result"]["sha256"]:
                raise ValueError("Audit checkpoint changed after selection")
            evaluated, predictions = evaluate_checkpoint(
                run["result"]["checkpoint"], manifest, task, "test", device
            )
            atomic_json(root / "audit-private" / f"{task}-{name}.json", predictions)
            results[task][name] = evaluated | dict(sha256=run["result"]["sha256"])
    report = dict(
        selection_hash=state["selection_hash"],
        tasks=results,
        test_previously_seen=True,
        used_for_selection=False,
        completed=timestamp(),
    )
    atomic_json(root / "test-audit.json", report)
    state["audit"] = report
    state["audit_status"] = "completed"
    atomic_json(
        root / "research-models.json",
        dict(
            selection_hash=state["selection_hash"],
            purpose="research-only; no service activation",
            models=[
                dict(
                    task=state["runs"][r]["task"],
                    recipe=state["runs"][r]["recipe"],
                    checkpoint=state["runs"][r]["result"]["checkpoint"],
                    sha256=state["runs"][r]["result"]["sha256"],
                    architecture=state["runs"][r]["result"]["architecture"],
                    decoding=state["runs"][r]["result"]["decoding"],
                    preprocessing=PREPROCESSING,
                    grades=list(range(TASKS[state["runs"][r]["task"]]["classes"])),
                )
                for r in state["stages"]["delivery"]["runs"]
            ],
        ),
    )


def run_study(state, *, through="delivery", max_new_runs=None):
    config = state["config"]
    if state["source_hash"] != source_fingerprint():
        raise ValueError("Source changed; do not mix implementations within a study")
    root = Path(config["study"]["output"])
    lock = root / "runner.lock"
    # Kernel lock is released on crash; a stale file is harmless.
    import msvcrt

    with lock.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        completed = 0
        state["status"] = "running"
        try:
            for stage in STAGES:
                if state["stages"][stage]["status"] == "completed":
                    if stage == through and through != "delivery":
                        return
                    continue
                if stage != "A":
                    prepare_stage(state, stage)
                state["stages"][stage]["status"] = "running"
                save_state(state)
                for identifier in state["stages"][stage]["runs"]:
                    run = state["runs"][identifier]
                    fresh = run["status"] != "completed"
                    execute_run(state, run)
                    completed += int(fresh)
                    if max_new_runs is not None and completed >= max_new_runs:
                        state["status"] = "scheduled_stop"
                        save_state(state)
                        return
                if stage == "C":
                    add_sensitivity(state)
                    for identifier in state["stages"]["C"]["sensitivity_runs"]:
                        run = state["runs"][identifier]
                        fresh = run["status"] != "completed"
                        execute_run(state, run)
                        completed += int(fresh)
                        if max_new_runs is not None and completed >= max_new_runs:
                            state["status"] = "scheduled_stop"
                            save_state(state)
                            return
                if stage == "D":
                    choose_models(state)
                state["stages"][stage]["status"] = "completed"
                save_state(state)
                if stage == through and through != "delivery":
                    state["status"] = "scheduled_stop"
                    save_state(state)
                    return
            audit(state)
            state["status"] = "completed"
            state.pop("active_run", None)
            save_state(state)
        except BaseException as error:
            state["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
            state["stages"][stage]["status"] = state["status"]
            state["failure_type"] = type(error).__name__
            save_state(state)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "report", "status", "worker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_STUDY)
    parser.add_argument("--through", choices=STAGES, default="delivery")
    parser.add_argument("--max-new-runs", type=int)
    parser.add_argument("--attempt", type=Path)
    parser.add_argument("--task", choices=list(TASKS))
    parser.add_argument("--outer", action="store_true")
    args = parser.parse_args()
    if args.max_new_runs is not None and args.max_new_runs < 1:
        parser.error("--max-new-runs must be positive")
    if args.command == "worker":
        if args.attempt is None or args.task is None:
            parser.error("worker requires --attempt and --task")
        try:
            worker(args.attempt, args.task, args.outer)
        except Exception as error:
            descriptions = {
                "TypeError": "결과 처리 중 자료형 또는 중복 필드 오류",
                "ValueError": "데이터·설정·가중치 계약 검사 실패",
                "FileNotFoundError": "필요한 로컬 파일을 찾을 수 없음",
                "PermissionError": "로컬 파일 접근 권한 오류",
                "OutOfMemoryError": "GPU 메모리 부족",
                "RuntimeError": "학습 또는 추론 실행 오류",
            }
            error_type = type(error).__name__
            atomic_json(
                args.attempt / "failure.json",
                dict(
                    error_type=error_type,
                    error_summary=descriptions.get(error_type, "실행 중 예외 발생"),
                    private_message=str(error),
                ),
            )
            raise
        return
    config = load_study(args.config)
    if args.command in ("report", "status"):
        state = read_json(Path(config["study"]["output"]) / "study.json")
    else:
        state = initialize(config)
    if args.command == "run":
        run_study(state, through=args.through, max_new_runs=args.max_new_runs)
    elif args.command == "report":
        from .study_report import publish_study

        publish_study(state)
    elif args.command == "status":
        print(
            json.dumps(
                dict(
                    status=state["status"],
                    updated=state["updated"],
                    stages={
                        k: dict(status=v["status"], runs=len(v["runs"]))
                        for k, v in state["stages"].items()
                    },
                ),
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
