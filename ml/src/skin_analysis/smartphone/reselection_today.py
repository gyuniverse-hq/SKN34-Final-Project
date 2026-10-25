"""Deadline-bounded 26-run study; two matched seeds, no old-test access."""

import argparse
import ast
import copy
import importlib.metadata
import json
import re
import shutil
import statistics
import tomllib
from datetime import datetime
from pathlib import Path

from ..config import PROJECT_ROOT
from .common import TASKS, digest, file_hash
from .reselection import (
    configure_attempt,
    execute_run,
    load_study,
    make_run,
    original_manifest,
    source_fingerprint,
    timestamp,
)
from .study_design import atomic_json, read_json

DEFAULT_TODAY = PROJECT_ROOT / "configs/nia_smartphone_reselection_today.toml"
TRAINING_FILES = (
    "ml/src/skin_analysis/config.py",
    "ml/src/skin_analysis/dataset.py",
    "ml/src/skin_analysis/runtime.py",
    "ml/src/skin_analysis/train.py",
    "ml/src/skin_analysis/smartphone/train.py",
    "ml/src/skin_analysis/smartphone/data.py",
    "ml/src/skin_analysis/smartphone/sam.py",
    "ml/src/skin_analysis/smartphone/backbones.py",
    "ml/src/skin_analysis/smartphone/common.py",
    "ml/src/skin_analysis/smartphone/losses.py",
    "ml/src/skin_analysis/smartphone/coral.py",
    "ml/src/skin_analysis/smartphone/ordinal_loss.py",
    "server/nia/metrics.py",
)
CASE_LABELS = {
    "ce": "일반 CE + AdamW",
    "sqrt": "제곱근 WCE·상한4 + AdamW",
    "sam": "제곱근 WCE·상한4 + SAM",
    "inverse": "역빈도 WCE·상한4 + AdamW",
    "uncapped": "제곱근 WCE·상한 없음 + AdamW",
}


def now():
    return datetime.now().astimezone()


def load_today(path=DEFAULT_TODAY):
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    today = raw["today"]
    if today["protocol"] != "reselection-today-v1" or today["seeds"] != [17, 42]:
        raise ValueError("Today protocol requires exactly seeds 17 and 42")
    base = load_study(PROJECT_ROOT / today["base_config"])
    for key in ("output", "reuse_study", "reports"):
        today[key] = str((PROJECT_ROOT / today[key]).resolve())
    stop = datetime.fromisoformat(today["training_deadline"])
    report = datetime.fromisoformat(today["report_deadline"])
    if stop.tzinfo is None or report.tzinfo is None or (report - stop).total_seconds() < 1800:
        raise ValueError("Reserve at least 30 minutes between aware training/report deadlines")
    base["study"].update(
        output=today["output"],
        reports=today["reports"],
        search_seeds=today["seeds"],
        max_attempts=today["max_attempts"],
    )
    return dict(config=base, today=today, estimated_minutes=raw["estimated_minutes"])


def cases():
    base = dict(
        backbone="resnet50",
        loss="weighted_cross_entropy",
        weight_exponent=0.5,
        class_weight_cap=4.0,
        batch_size=16,
        lr_multiplier=1.0,
        optimizer="adamw",
    )
    return {
        "ce": base
        | dict(loss="unweighted_cross_entropy", weight_exponent=0.0, class_weight_cap=None),
        "sqrt": base,
        "sam": base | dict(optimizer="sam_adamw", sam_rho=0.05),
        "inverse": base | dict(weight_exponent=1.0),
        "uncapped": base | dict(class_weight_cap=None),
    }


def training_hash(repo):
    payload = {name: file_hash(Path(repo) / name) for name in TRAINING_FILES}
    # Include worker TF32/AMP setup and config resolution, while permitting report-only changes.
    module = ast.parse(
        (Path(repo) / "ml/src/skin_analysis/smartphone/reselection.py").read_text(encoding="utf-8")
    )
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("worker", "configure_attempt"):
            payload[f"worker-policy:{node.name}"] = ast.dump(node, include_attributes=False)
    return digest(payload)


def check_reuse(state, source):
    """Only orchestration changed: verify actual training code AND resolved config."""
    root = Path(state["settings"]["today"]["reuse_study"])
    snapshot = root / "paused-source"
    current_hash, previous_hash = training_hash(PROJECT_ROOT.parent), training_hash(snapshot)
    if current_hash != previous_hash or source["data_fingerprint"] != state["data_fingerprint"]:
        raise ValueError("Cannot reuse runs with different training source/data")
    state["training_source_hash"] = current_hash
    imported = []
    for run in state["runs"].values():
        previous = source["runs"].get(run["id"])
        if not previous or previous["status"] != "completed":
            continue
        if previous["recipe"] != run["recipe"] or previous["seed"] != run["seed"]:
            raise ValueError("Reuse identity differs")
        artifact = Path(previous["result"]["checkpoint"])
        if file_hash(artifact) != previous["result"]["sha256"]:
            raise ValueError("Reused checkpoint changed")
        for package, version in previous["result"]["environment"]["packages"].items():
            if importlib.metadata.version(package) != version:
                raise ValueError("Reused checkpoint package environment differs")
        original_config = read_json(Path(previous["result"]["attempt_root"]) / "config.json")
        desired = configure_attempt(state, run, Path("unused"))
        excluded = {"output", "expected_source_hash"}
        if {k: v for k, v in original_config["train"].items() if k not in excluded} != {
            k: v for k, v in desired["train"].items() if k not in excluded
        } or original_config["data"] != desired["data"]:
            raise ValueError("Reused checkpoint has different training settings")
        run.update(
            status="completed",
            result=copy.deepcopy(previous["result"]),
            inherited_from=source["source_hash"],
            inherited_study=str(root),
        )
        imported.append(run["id"])
    state["reused_runs"] = imported


def initialize(settings):
    root = Path(settings["today"]["output"])
    if (root / "study.json").exists():
        state = read_json(root / "study.json")
        if state["settings"] != settings or state["source_hash"] != source_fingerprint():
            raise ValueError("Today study config/source changed; keep existing results separate")
        return state
    manifest = original_manifest(settings["config"])
    state = dict(
        schema="skin-reselection-today-v1",
        settings=settings,
        config=settings["config"],
        source_hash=source_fingerprint(),
        data_fingerprint=manifest["fingerprint"],
        created=timestamp(),
        updated=timestamp(),
        status="planned",
        runs={},
        groups=[],
        stopped_full_study=True,
        test_access=False,
    )
    recipes = cases()
    ordered = [(task, case, True) for task in TASKS for case in ("ce", "sqrt", "sam")]
    ordered += [("pore", "uncapped", False)]
    ordered += [(task, "inverse", False) for task in TASKS]
    for task, case, core in ordered:
        identifiers = []
        for seed in settings["today"]["seeds"]:
            run = make_run(state["config"], task, recipes[case], seed)
            run["case"] = case
            state["runs"][run["id"]] = run
            identifiers.append(run["id"])
        state["groups"].append(dict(task=task, case=case, core=core, runs=identifiers))
    source = read_json(Path(settings["today"]["reuse_study"]) / "study.json")
    check_reuse(state, source)
    root.mkdir(parents=True, exist_ok=True)
    reports = Path(settings["today"]["reports"])
    archived = reports / "experiments/full-study-paused"
    archived.mkdir(parents=True, exist_ok=True)
    for path in (
        reports / "experiment-summary.md",
        reports / "final-model-report.md",
        reports / "reselection.metrics.json",
    ):
        if path.exists() and not (archived / path.name).exists():
            shutil.copy2(path, archived / path.name)
            if path.suffix == ".md":
                text = (archived / path.name).read_text(encoding="utf-8")
                text = re.sub(
                    r"\]\((?!https?://|#)([^)]+)\)",
                    lambda match: "](../../" + match.group(1) + ")",
                    text,
                )
                (archived / path.name).write_text(text, encoding="utf-8")
    atomic_json(
        root / "protocol.json",
        dict(
            settings=settings,
            source_hash=state["source_hash"],
            training_source_hash=state["training_source_hash"],
            reused_runs=state["reused_runs"],
        ),
    )
    persist(state)
    return state


def persist(state):
    from .today_report import publish

    state["updated"] = timestamp()
    atomic_json(Path(state["settings"]["today"]["output"]) / "study.json", state)
    publish(state)


def estimate_seconds(state, run):
    bucket = [
        r["result"]["execution_wall_seconds"]
        for r in state["runs"].values()
        if r["status"] == "completed"
        and r["task"] == run["task"]
        and r["recipe"]["optimizer"] == run["recipe"]["optimizer"]
    ]
    if bucket:
        return statistics.median(bucket)
    key = f"{run['task']}_{run['recipe']['optimizer']}"
    return state["settings"]["estimated_minutes"][key] * 60


def group_fits(state, group, instant):
    remaining = (
        datetime.fromisoformat(state["settings"]["today"]["training_deadline"]) - instant
    ).total_seconds()
    budget = sum(
        estimate_seconds(state, state["runs"][r])
        for r in group["runs"]
        if state["runs"][r]["status"] != "completed"
    )
    return remaining > budget * state["settings"]["today"]["pair_safety_factor"]


def run_today(state):
    import msvcrt

    root = Path(state["settings"]["today"]["output"])
    if state["source_hash"] != source_fingerprint():
        raise ValueError("Today source changed after registration")
    with (root / "runner.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        state["status"] = "running"
        persist(state)
        try:
            for group in state["groups"]:
                pending = [
                    state["runs"][r]
                    for r in group["runs"]
                    if state["runs"][r]["status"] != "completed"
                ]
                if not pending:
                    continue
                if not group_fits(state, group, now()):
                    group["deferred_reason"] = "마감 전 seed 쌍을 완주할 시간 부족"
                    for run in pending:
                        run["status"] = "deferred"
                    persist(state)
                    if group["core"]:
                        break
                    continue
                for run in pending:
                    remaining = (
                        datetime.fromisoformat(state["settings"]["today"]["training_deadline"])
                        - now()
                    ).total_seconds()
                    execute_run(state, run, persist=persist, timeout_seconds=max(0, remaining))
            state["status"] = (
                "completed"
                if all(r["status"] == "completed" for r in state["runs"].values())
                else "deadline_closed"
            )
        except TimeoutError:
            state["status"] = "deadline_closed"
        except KeyboardInterrupt:
            state["status"] = "paused"
            raise
        except Exception as error:
            state["status"] = "failed"
            state["failure_type"] = type(error).__name__
            raise
        finally:
            if state["status"] == "deadline_closed":
                for run in state["runs"].values():
                    if run["status"] == "planned":
                        run["status"] = "deferred"
            if state["status"] != "running":
                state.pop("active_run", None)
            persist(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "report", "status"))
    parser.add_argument("--config", type=Path, default=DEFAULT_TODAY)
    args = parser.parse_args()
    settings = load_today(args.config)
    if args.command in ("init", "run"):
        state = initialize(settings)
    else:
        state = read_json(Path(settings["today"]["output"]) / "study.json")
    if args.command == "run":
        run_today(state)
    elif args.command == "report":
        from .today_report import publish

        publish(state)
    elif args.command == "status":
        print(
            json.dumps(
                dict(
                    status=state["status"],
                    completed=sum(r["status"] == "completed" for r in state["runs"].values()),
                    total=len(state["runs"]),
                    reused=len(state["reused_runs"]),
                    training_deadline=settings["today"]["training_deadline"],
                ),
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
