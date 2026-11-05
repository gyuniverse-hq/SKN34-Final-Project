"""Reproducible evaluation of all configured NIA tasks and the selected acne model.

No fitting, checkpoint rewriting, split changes, image exports, or test threshold tuning.
Detailed predictions stay in an ignored local output directory.
"""

import argparse
import importlib.metadata
import json
import statistics
import subprocess
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import cv2
import torch

from ml.src.skin_analysis.acne.common import archive_path, load_config, load_manifest
from ml.src.skin_analysis.acne.data import prepare_image
from server.acne.engine import AcneEngine

from .catalog import TASKS
from .dataset import DESCRIPTOR, prepare_dataset, read_split
from .engine import Engine, sha256
from .imaging import prepare
from .metrics import classification, regression

DEVICES = ("smart_phone", "digital_camera", "smart_pad")
CLASS_KEYS = (
    "n",
    "accuracy",
    "macro_precision",
    "macro_recall",
    "macro_f1",
    "weighted_precision",
    "weighted_recall",
    "weighted_f1",
    "per_grade",
    "confusion",
)
REGRESSION_KEYS = ("n", "mae", "mse", "rmse", "r2", "r2_undefined_reason")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def distribution(values):
    return dict(
        min=min(values), max=max(values), mean=statistics.mean(values), sd=statistics.pstdev(values)
    )


def score_rows(rows, mode, classes=None, ordinal=True):
    if not rows:
        return None
    truth = [row["truth"] for row in rows]
    predicted = [row["prediction"] for row in rows]
    if mode == "class":
        result = classification(truth, predicted, classes)
        result = {key: result[key] for key in CLASS_KEYS}
        if ordinal:
            result["within_one"] = sum(
                abs(a - p) <= 1 for a, p in zip(truth, predicted, strict=True)
            ) / len(rows)
        counts = Counter(truth)
        result["evaluation_majority_constant_accuracy_descriptive_only"] = max(
            counts.values()
        ) / len(rows)
    else:
        result = regression(truth, predicted)
        result = {key: result[key] for key in REGRESSION_KEYS}
        result.update(
            accuracy=None,
            accuracy_reason="no_predeclared_tolerance_for_continuous_targets",
            truth_distribution=distribution(truth),
            prediction_distribution=distribution(predicted),
        )
    return result


def task_audit(root, mode, device, areas, rows, task=None):
    """Scope subject overlap to this model's areas, never all tasks in a split."""
    cohorts, hashes = {}, {}
    for name in ("train", "val", "test"):
        path = root / f"split/{mode}/{device}/1_{name}set_info.json"
        data = read_split(path)
        if all(area in data for area in areas):
            cohorts[name] = {entry for area in areas for entry in data[area]}
        elif task and task.split("/")[1] in data:
            # Supplied train/val use task keys; test uses anatomical area keys.
            cohorts[name] = set(data[task.split("/")[1]])
        else:
            raise ValueError(f"No verified task/area mapping in {path}")
        hashes[name] = sha256(path)
    available_path = root / f"split/{mode}/{device}/1_available_testset_info.json"
    available = read_split(available_path)
    available_ids = {entry for area in areas for entry in available[area]}
    actual_ids = {row["id"] for row in rows}
    if actual_ids != available_ids or not available_ids <= cohorts["test"]:
        raise ValueError("Evaluation samples differ from the declared available official subset")
    subjects = {DESCRIPTOR.fullmatch(entry)[1] for entry in actual_ids}
    comparisons = {}
    known_people = set()
    for name in ("train", "val"):
        people = {DESCRIPTOR.fullmatch(entry)[1] for entry in cohorts[name]}
        known_people.update(people)
        comparisons[name] = dict(
            subject_overlap=len(subjects & people), roi_id_overlap=len(actual_ids & cohorts[name])
        )
    independent = subjects - known_people
    return dict(
        official_test_rois=len(cohorts["test"]),
        evaluated_rois=len(rows),
        excluded_rois=len(cohorts["test"] - actual_ids),
        subjects=len(subjects),
        comparisons=comparisons,
        no_train_val_overlap_subjects=len(independent),
        independent_subset=sorted(independent),
        split_sha256={**hashes, "available_test": sha256(available_path)},
    )


def batch_predict(
    records,
    prepare_record,
    model,
    device,
    batch_size,
    workers,
    mode,
    multiplier=1,
    threshold=0.5,
    label="",
):
    rows = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool, torch.inference_mode():
        for start in range(0, len(records), batch_size):
            selected = records[start : start + batch_size]
            tensors = list(pool.map(prepare_record, selected))
            tensor = torch.cat(tensors).to(device)
            output = model(tensor)
            if not torch.isfinite(output).all():
                raise ValueError("Non-finite model output; evaluation aborted")
            if mode == "class":
                predictions = output.argmax(dim=1).cpu().tolist()
                scores = [None] * len(selected)
            elif mode == "binary":
                scores = output.float().sigmoid().flatten().cpu().tolist()
                predictions = [int(value >= threshold) for value in scores]
            else:
                predictions = (output.flatten() * multiplier).cpu().tolist()
                scores = [None] * len(selected)
            for record, predicted, score in zip(selected, predictions, scores, strict=True):
                row = {key: record[key] for key in ("id", "area", "truth")}
                row["prediction"] = predicted
                if score is not None:
                    row["score"] = score
                rows.append(row)
            if len(rows) % (batch_size * 16) == 0 or len(rows) == len(records):
                print(
                    json.dumps(
                        dict(
                            stage="inference",
                            dataset=label,
                            done=len(rows),
                            total=len(records),
                            elapsed_s=round(time.perf_counter() - started, 1),
                        )
                    ),
                    flush=True,
                )
    return rows


def evaluate_nia(config, root, output, devices, batch_size, workers):
    results = []
    if len(config.get("models", [])) != len(TASKS) or {m["task"] for m in config["models"]} != set(
        TASKS
    ):
        raise ValueError("All ten original NIA tasks must be configured exactly once")
    for model_config in config["models"]:
        engine = Engine(model_config)
        engine.load()
        mode, classes, multiplier, _ = TASKS[engine.config["task"]]
        model_result = dict(
            task=engine.config["task"],
            id=engine.config["id"],
            mode=mode,
            checkpoint_sha256=engine.config["sha256"],
            unit=engine.config.get("unit", "grade"),
            outputs=classes,
            devices={},
            source=engine.config["source"],
        )
        all_rows = []
        for device in devices:
            areas = list(engine.config["areas"])
            request = dict(
                dataset_root=str(root),
                areas=areas,
                test_split=f"split/{mode}/{device}/1_available_testset_info.json",
            )
            records, _ = prepare_dataset(request, engine.config, config["dataset_roots"])
            audit = task_audit(root, mode, device, areas, records, engine.config["task"])

            def prepare_record(record, configured_areas=engine.config["areas"]):
                return prepare(
                    record["path"].read_bytes(),
                    record["bbox"],
                    configured_areas[record["area"]][0],
                    record["precropped"],
                    include_preview=False,
                )[0]

            # Verify the batching path against the existing inference engine before the cohort run.
            first = records[0]
            reference = engine.predict(
                first["path"].read_bytes(),
                first["area"],
                first["bbox"],
                first["precropped"],
                preview=False,
            )["prediction"]
            check = batch_predict(
                records[:1],
                prepare_record,
                engine.model,
                engine.device,
                1,
                1,
                mode,
                multiplier,
                label="parity-check",
            )[0]["prediction"]
            expected = reference["grade" if mode == "class" else "value"]
            if abs(check - expected) > (1e-4 * max(1, abs(expected))):
                raise ValueError("Batch evaluation does not match the existing engine")
            rows = batch_predict(
                records,
                prepare_record,
                engine.model,
                engine.device,
                batch_size,
                workers,
                mode,
                multiplier,
                label=f"{engine.config['task']}/{device}",
            )
            independent = set(audit.pop("independent_subset"))
            per_area = {
                area: score_rows([r for r in rows if r["area"] == area], mode, classes)
                for area in areas
            }
            model_result["devices"][device] = dict(
                metrics=score_rows(rows, mode, classes),
                audit=audit,
                areas=per_area,
                no_train_val_subject_overlap_metrics=score_rows(
                    [r for r in rows if DESCRIPTOR.fullmatch(r["id"])[1] in independent],
                    mode,
                    classes,
                ),
                parity=dict(reference=expected, evaluation=check, checked=True),
            )
            all_rows.extend([{**r, "device": device} for r in rows])
            write_json(output / (engine.config["task"].replace("/", "-") + f"-{device}.json"), rows)
            print(
                json.dumps(
                    dict(
                        stage="dataset_complete",
                        task=engine.config["task"],
                        device=device,
                        metrics=model_result["devices"][device]["metrics"],
                        audit=audit,
                    )
                ),
                flush=True,
            )
        model_result["all_devices_pooled"] = score_rows(all_rows, mode, classes)
        results.append(model_result)
        write_json(output / "nia-progress.json", results)
        del engine
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return results


def evaluate_acne(config, output, batch_size, workers):
    engine = AcneEngine(config["acne"])
    engine.load()
    settings = load_config()
    manifest = load_manifest(settings)
    if engine.bundle["manifest_fingerprint"] != manifest["fingerprint"]:
        raise ValueError("Acne bundle and audited dataset fingerprint differ")
    records_by_split = {
        split: [
            {**row, "truth": row["label"], "area": "full_image"}
            for row in manifest["records"]
            if row["split"] == split
        ]
        for split in ("test", "official_audit")
    }
    result = dict(
        task="acne/binary",
        mode="binary",
        checkpoint_sha256=config["acne"]["sha256"],
        threshold=engine.bundle["threshold"],
        datasets={},
        manifest_fingerprint=manifest["fingerprint"],
        validation_status=engine.bundle["validation_status"],
    )
    with ExitStack() as stack:
        archives = {row["archive"] for rows in records_by_split.values() for row in rows}
        handles = {
            name: stack.enter_context(zipfile.ZipFile(archive_path(manifest["root"], name)))
            for name in archives
        }

        def prepare_record(row):
            return prepare_image(handles[row["archive"]].read(row["member"])).unsqueeze(0)

        for split, records in records_by_split.items():
            rows = batch_predict(
                records,
                prepare_record,
                engine.model,
                engine.device,
                batch_size,
                workers,
                "binary",
                threshold=result["threshold"],
                label=f"acne/{split}",
            )
            metrics = score_rows(rows, "class", 2, ordinal=False)
            positive = metrics["per_grade"][1]
            metrics.update(
                precision_acne=positive["precision"],
                recall_acne=positive["recall"],
                f1_acne=positive["f1"],
            )
            result["datasets"][split] = dict(
                metrics=metrics, groups=len({r["group_id"] for r in records}), real_photos=False
            )
            write_json(output / f"acne-{split}.json", rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="server/nia/config.local.json")
    parser.add_argument("--dataset-root", default="nia-private/evaluation-data-verified")
    parser.add_argument("--output", required=True)
    parser.add_argument("--devices", nargs="+", choices=DEVICES, default=list(DEVICES))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.batch_size < 1 or args.workers < 1:
        parser.error("batch size and workers must be positive")
    output = Path(args.output).resolve()
    if not output.is_relative_to((Path.cwd() / "ml/runs").resolve()):
        parser.error("Detailed evaluation outputs must stay inside ignored ml/runs/")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    cv2.setNumThreads(1)
    torch.manual_seed(42)
    torch.backends.cudnn.benchmark = False
    config_path = Path(args.config).resolve(strict=True)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    report = dict(
        schema="skin-model-benchmark-v1",
        status="running",
        started_utc=datetime.now(UTC).isoformat(),
        seed=42,
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_sha256={
            name: sha256(Path(__file__).with_name(name))
            for name in ("benchmark.py", "metrics.py", "engine.py", "imaging.py", "dataset.py")
        },
        settings=dict(
            devices=args.devices,
            batch_size=args.batch_size,
            workers=args.workers,
            precision="float32",
            test_threshold_fitting=False,
        ),
        additional_metrics=["RMSE", "within_one_grade_accuracy"],
        versions={
            p: importlib.metadata.version(p)
            for p in (
                "torch",
                "torchvision",
                "numpy",
                "Pillow",
                "opencv-python-headless",
                "scikit-learn",
            )
        },
        device=str(torch.cuda.get_device_name() if torch.cuda.is_available() else "cpu"),
    )
    write_json(output / "run.json", report)
    try:
        report["nia"] = evaluate_nia(
            config,
            Path(args.dataset_root).resolve(strict=True),
            output,
            args.devices,
            args.batch_size,
            args.workers,
        )
        report["acne"] = evaluate_acne(config, output, args.batch_size, args.workers)
        report.update(status="complete", elapsed_seconds=time.perf_counter() - started)
        write_json(output / "report.json", report)
        print(
            json.dumps(
                dict(stage="complete", output=str(output), seconds=report["elapsed_seconds"])
            ),
            flush=True,
        )
    except Exception as error:
        report.update(
            status="failed", error=str(error), elapsed_seconds=time.perf_counter() - started
        )
        write_json(output / "run.json", report)
        raise


if __name__ == "__main__":
    main()
