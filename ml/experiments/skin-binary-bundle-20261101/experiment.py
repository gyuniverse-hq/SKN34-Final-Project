"""Prepare the binary wrinkle/pigmentation expansion; setup never trains or infers."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

HERE = Path(__file__).resolve().parent
ML = HERE.parents[1]
sys.path[:0] = [str(ML / "src"), str(ML.parent)]

from skin_analysis.config import digest, write_json  # noqa: E402
from skin_analysis.dataset import seed_worker  # noqa: E402
from skin_analysis.runtime import (  # noqa: E402
    capture_rng,
    cpu_tree,
    restore_rng,
    save_checkpoint,
    seed_all,
    select_cuda,
)
from skin_analysis.smartphone.common import (  # noqa: E402
    TASKS,
    assert_disjoint,
    file_hash,
    load_manifest,
)
from skin_analysis.smartphone.data import GradeDataset  # noqa: E402
from skin_analysis.smartphone.train import verify_crops  # noqa: E402

BASE = HERE / "pore_reference.py"
SPEC = importlib.util.spec_from_file_location("skin_binary_pore_reference", BASE)
if SPEC is None or SPEC.loader is None:
    raise ImportError(str(BASE))
reference = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reference
SPEC.loader.exec_module(reference)

OUTPUT = ML / "runs/skin-binary-bundle-20261101"
SOURCE = ML / "runs/mobilenet-skin-bundle-20261030/data/manifest.json"
PORE_MANIFEST = ML / "runs/pore-no-preproc-split-seed42-20261101/manifest/manifest.json"
PORE_RESULT = ML / "runs/pore-preprocessing-ablation-20261101/fixed-texture"
OLD_BUNDLE = ML / "runs/skin-type-mobilenet-20261030/bundle-four-models-20261030"
SETTINGS = dict(reference.SETTINGS)
NEW_TASKS = ("pigmentation", "wrinkle")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(records, classes):
    return {
        split: {
            "roi": len(rows := [r for r in records if r["split"] == split]),
            "subjects": len({r["subject"] for r in rows}),
            "grades": [sum(r["truth"] == grade for r in rows) for grade in range(classes)],
            "binary": [sum(int(r["truth"] >= 3) == label for r in rows) for label in (0, 1)],
        }
        for split in ("train", "valid", "test")
    }


def expand_training(dataset, classes):
    original = list(dataset.records)
    pools = [[r for r in original if r["truth"] == grade] for grade in range(classes)]
    counts = [len(pool) for pool in pools]
    if not all(counts):
        raise ValueError(f"A training grade is absent: {counts}")
    draws = [math.ceil(math.sqrt(n * max(counts))) for n in counts]
    for grade, pool in enumerate(pools):
        random.Random(42 + grade).shuffle(pool)
        for index in range(draws[grade] - counts[grade]):
            record = pool[index % len(pool)]
            dataset.records.append(
                {
                    **record,
                    "id": f"{record['id']}:additional:{index // len(pool) + 1}",
                }
            )
    return counts, draws


def setup():
    source = load_manifest({"data": {"output": str(SOURCE.parent)}})
    pore = load_manifest({"data": {"output": str(PORE_MANIFEST.parent)}})
    if source.get("fixed_texture_preprocessing_baked") is not True:
        raise ValueError("Expected the once-preprocessed fixed-texture cache")
    if any(
        source.get("experiment_texture_preprocessing", {}).get(key) != value
        for key, value in reference.PIPELINE.items()
    ):
        raise ValueError("Fixed preprocessing differs from the pore reference")
    verify_crops(source)
    assignment = {r["subject"]: r["split"] for r in pore["records"]}
    if "0427" in assignment:
        raise ValueError("Pore exclusion was not applied")
    contracts = {}
    all_records = list(pore["records"])
    for task in NEW_TASKS:
        if (OUTPUT / task / "last.pt").exists() or (OUTPUT / task / "summary.json").exists():
            raise FileExistsError(f"Training artifacts exist; preserve the reviewed setup: {task}")
        rows = copy.deepcopy([r for r in source["records"] if r["task"] == task])
        unmatched = {r["subject"] for r in rows} - assignment.keys()
        if unmatched != {"0427"}:
            raise ValueError(f"Unexpected subjects without pore assignment: {unmatched}")
        # The documented exclusion applies to pore only. Subject 0427 retains
        # the original Test membership for the other two annotation tasks.
        for row in rows:
            row["split"] = assignment.get(row["subject"], row["split"])
        assert_disjoint(rows)
        all_records.extend(rows)
        classes = TASKS[task]["classes"]
        manifest = copy.deepcopy(source)
        manifest.pop("fingerprint")
        manifest.update(
            records=rows,
            summary={task: summarize(rows, classes)},
            split_method=(
                "shared subject assignment from new pore seed42 split; "
                "0427 retained in source Test for non-pore tasks"
            ),
            subject_split_reference=str(PORE_MANIFEST),
            subject_split_fingerprint=pore["fingerprint"],
            source_manifest_fingerprint=source["fingerprint"],
        )
        manifest["source_photo_count"] = len({r["image_sha256"] for r in rows})
        manifest["fingerprint"] = digest(manifest)
        target = OUTPUT / task / "data/manifest.json"
        old = read(target) if target.exists() else None
        if old and old != manifest:
            raise ValueError(f"Prepared split changed: {target}")
        write_json(target, manifest)
        data = GradeDataset(manifest, task, "train", training=True, training_seed=42)
        counts, draws = expand_training(data, classes)
        sampler = reference.GradeDiverseBatchSampler(data, 16, torch.Generator().manual_seed(42))
        seen = [index for batch in sampler for index in batch]
        if sorted(seen) != list(range(len(data))):
            raise ValueError("Sampler must expose every original and additional training row")
        binary = [sum(counts[:3]), sum(counts[3:])]
        contract = {
            "schema": "skin-binary-expansion-v1",
            "task": task,
            "architecture": "mobilenet_v3_large",
            "initialization": "IMAGENET1K_V2",
            "head": "960 -> 1280 -> Hardswish -> Dropout(0.2) -> 1 logit -> sigmoid",
            "label_mapping": [int(g >= 3) for g in range(classes)],
            "classes": ["양호", "유의"],
            "threshold": 0.5,
            "settings": SETTINGS,
            "preprocessing": reference.PIPELINE,
            "preprocessing_baked_in_cache": True,
            "random_train_augmentation": {
                "degrees": 5,
                "translate": 0.02,
                "brightness": 0.1,
                "contrast": 0.1,
                "saturation": 0.05,
                "horizontal_flip": False,
            },
            "sampling": (
                "every original row + sqrt additional draws by original grade; "
                "diverse-grade batches"
            ),
            "original_grade_counts": counts,
            "draws_by_original_grade": draws,
            "draws_per_epoch": len(data),
            "steps_per_epoch": len(sampler),
            "class_weights": [sum(counts) / (2 * n) for n in binary],
            "loss": (
                "binary-original-frequency inverse-weighted BCEWithLogitsLoss; "
                "exponent=1; no Huber or original-grade alpha weight"
            ),
            "checkpoint_selection": (
                "Validation binary Macro-F1 maximum, unweighted BCE minimum on tie"
            ),
            "test_policy": (
                "explicit evaluate action only after Validation checkpoint selection; "
                "no Test-based tuning"
            ),
            "splits": manifest["summary"][task],
            "manifest_fingerprint": manifest["fingerprint"],
            "cache_sha256": manifest["pixel_cache"]["sha256"],
            "pore_subject_split_fingerprint": pore["fingerprint"],
            "exclusion_scope": "0427 excluded for pore only; retained in Test for this task",
            "areas": TASKS[task]["areas"],
            "code_sha256": {
                "experiment.py": file_hash(__file__),
                "pore_reference.py": file_hash(BASE),
            },
        }
        contracts[task] = contract
        write_json(
            OUTPUT / task / "setup.json", {"contract": contract, "status": "prepared_not_started"}
        )
    assert_disjoint(all_records)
    write_json(OUTPUT / "setup.json", {"status": "prepared_not_started", "tasks": contracts})
    return contracts


def inputs(task):
    manifest = load_manifest({"data": {"output": str(OUTPUT / task / "data")}})
    contract = read(OUTPUT / task / "setup.json")["contract"]
    if manifest["fingerprint"] != contract["manifest_fingerprint"]:
        raise ValueError("Manifest and contract differ")
    verify_crops(manifest)
    return manifest, contract


def metrics(grades, probabilities, classes):
    grades = np.asarray(grades, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    if (
        not len(grades)
        or p.shape != grades.shape
        or not np.isfinite(p).all()
        or (p < 0).any()
        or (p > 1).any()
        or (grades < 0).any()
        or (grades >= classes).any()
    ):
        raise ValueError("Invalid binary metrics input")
    truth, predicted = (grades >= 3).astype(int), (p >= 0.5).astype(int)
    matrix = np.bincount(truth * 2 + predicted, minlength=4).reshape(2, 2)
    per_class = []
    for label, name in enumerate(("양호", "유의")):
        tp = int(matrix[label, label])
        support, selected = int(matrix[label].sum()), int(matrix[:, label].sum())
        precision = tp / selected if selected else 0.0
        recall = tp / support if support else 0.0
        per_class.append(
            dict(
                label=label,
                name=name,
                support=support,
                precision=precision,
                recall=recall,
                f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            )
        )
    high = grades >= 4
    return {
        "n": len(grades),
        "accuracy": float((truth == predicted).mean()),
        "confusion": matrix.tolist(),
        "per_class": per_class,
        **{
            f"macro_{key}": float(np.mean([r[key] for r in per_class]))
            for key in ("precision", "recall", "f1")
        },
        "cross_entropy": float(
            -(
                truth * np.log(np.clip(p, 1e-12, 1))
                + (1 - truth) * np.log(np.clip(1 - p, 1e-12, 1))
            ).mean()
        ),
        "grade4plus_support": int(high.sum()),
        "grade4plus_miss_rate": float((predicted[high] == 0).mean()) if high.any() else None,
        "per_original_grade": [
            {
                "grade": grade,
                "support": int((mask := grades == grade).sum()),
                "predicted_caution_rate": float(predicted[mask].mean()) if mask.any() else None,
            }
            for grade in range(classes)
        ],
    }


@torch.inference_mode()
def evaluate_model(model, dataset, device, classes, description):
    model.eval()
    loader = reference.eval_loader(dataset)
    probabilities, grades = [], []
    for images, labels, _ in tqdm(loader, desc=description, leave=False):
        probabilities.extend(
            model(images.to(device, non_blocking=True)).float().reshape(-1).sigmoid().cpu().tolist()
        )
        grades.extend(labels.tolist())
    return metrics(grades, probabilities, classes), probabilities


def train(task, device):
    manifest, contract = inputs(task)
    output = OUTPUT / task
    if (output / "last.pt").exists():
        raise FileExistsError("Training output exists; do not overwrite a previous run")
    data = GradeDataset(manifest, task, "train", training=True, training_seed=42)
    real = GradeDataset(manifest, task, "train")
    valid = GradeDataset(manifest, task, "valid")
    classes = len(contract["label_mapping"])
    counts, draws = expand_training(data, classes)
    if counts != contract["original_grade_counts"] or draws != contract["draws_by_original_grade"]:
        raise ValueError("Training quotas differ from the reviewed setup")
    seed_all(42)
    model = reference.GradeModel(1, pretrained=True, backbone="mobilenet_v3_large").to(device)
    seed_all(42)
    generator = torch.Generator().manual_seed(42)
    loader = DataLoader(
        data,
        batch_sampler=reference.GradeDiverseBatchSampler(data, 16, generator),
        num_workers=SETTINGS["train_workers"],
        pin_memory=True,
        persistent_workers=SETTINGS["train_workers"] > 0,
        worker_init_fn=seed_worker,
        generator=torch.Generator().manual_seed(100042),
    )
    loader.micro_batch_size = 16
    criterion = reference.BalancedBinaryLoss(contract["class_weights"]).to(device)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    optimizer, scheduler = reference.optimizer_for(model, True), None
    best_key, best_epoch, stale, history = (-float("inf"), -float("inf")), 0, 0, []
    for epoch in range(100):
        if epoch == 1:
            optimizer = reference.optimizer_for(model, False)
            scheduler = reference.scheduler_for(optimizer)
            stale = 0
        data.set_epoch(epoch)
        started = time.perf_counter()
        lr_used = [group["lr"] for group in optimizer.param_groups]
        loss = reference.sam_train_epoch(
            model,
            reference.ProgressLoader(loader, f"{task} | {epoch + 1}/100"),
            optimizer,
            criterion,
            device,
            scaler,
            16,
            True,
            rho=0.05,
        )
        state = capture_rng(generator)
        try:
            train_metrics, _ = evaluate_model(model, real, device, classes, "Train real")
            valid_metrics, _ = evaluate_model(model, valid, device, classes, "Validation")
        finally:
            restore_rng(state, generator)
        key = (valid_metrics["macro_f1"], -valid_metrics["cross_entropy"])
        selected = key > best_key
        if selected:
            best_key, best_epoch, stale = key, epoch + 1, 0
        elif epoch >= 1:
            stale += 1
        if scheduler:
            scheduler.step(valid_metrics["macro_f1"])
        if model._sam_steps != contract["steps_per_epoch"]:
            raise RuntimeError("Unexpected sample/update coverage")
        row = dict(
            epoch=epoch + 1,
            train_loss=float(loss),
            train_real=train_metrics,
            valid=valid_metrics,
            selected=selected,
            stale_epochs=stale,
            lr_used=lr_used,
            lr_next=[group["lr"] for group in optimizer.param_groups],
            samples_seen=len(data),
            sam_steps=model._sam_steps,
            seconds=time.perf_counter() - started,
        )
        history.append(row)
        checkpoint = dict(
            schema="skin-binary-expansion-v1",
            contract=contract,
            epoch=epoch + 1,
            model_state=cpu_tree(model.network.state_dict()),
            optimizer_state=cpu_tree(optimizer.state_dict()),
            scaler_state=scaler.state_dict(),
            scheduler_state=scheduler.state_dict() if scheduler else None,
            rng_state=capture_rng(generator),
            history=history,
            best_epoch=best_epoch,
            best_key=list(best_key),
            stale=stale,
        )
        save_checkpoint(output / "last.pt", checkpoint)
        if selected:
            save_checkpoint(output / "best.pt", checkpoint)
        write_json(output / "history.json", history)
        print(
            json.dumps(
                dict(
                    task=task,
                    epoch=epoch + 1,
                    train_f1=train_metrics["macro_f1"],
                    valid_f1=valid_metrics["macro_f1"],
                    stale=stale,
                )
            ),
            flush=True,
        )
        if epoch >= 1 and stale >= 10:
            break
    write_json(
        output / "summary.json",
        dict(
            task=task,
            contract=contract,
            epochs_run=len(history),
            best_epoch=best_epoch,
            best_validation=history[best_epoch - 1]["valid"],
            status="trained_test_pending",
        ),
    )


def evaluate_test(task, device):
    manifest, contract = inputs(task)
    output = OUTPUT / task
    summary = read(output / "summary.json")
    if "candidate_test" in summary:
        raise FileExistsError("Final Test already evaluated; do not repeatedly evaluate")
    checkpoint = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    model = reference.GradeModel(1, pretrained=False, backbone="mobilenet_v3_large").to(device)
    model.network.load_state_dict(checkpoint["model_state"], strict=True)
    dataset = GradeDataset(manifest, task, "test")
    result, scores = evaluate_model(
        model, dataset, device, len(contract["label_mapping"]), "Final Test"
    )
    predictions = [
        dict(
            id=r["id"],
            subject=r["subject"],
            original_grade=r["truth"],
            truth=int(r["truth"] >= 3),
            probability_caution=p,
            predicted=int(p >= 0.5),
        )
        for r, p in zip(dataset.records, scores, strict=True)
    ]
    write_json(output / "test-predictions.json", predictions)
    summary.update(candidate_test=result, status="evaluated")
    write_json(output / "summary.json", summary)
    import report

    report.write_report(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("setup", "train", "evaluate"), nargs="?", default="setup"
    )
    parser.add_argument("--task", choices=(*NEW_TASKS, "all"), default="all")
    parser.add_argument("--gpu-uuid", default=reference.DEFAULT_GPU)
    args = parser.parse_args()
    if args.action == "setup":
        contracts = setup()
        print(
            json.dumps(
                {task: contract["splits"] for task, contract in contracts.items()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    device = select_cuda(args.gpu_uuid)
    for task in NEW_TASKS if args.task == "all" else (args.task,):
        (train if args.action == "train" else evaluate_test)(task, device)


if __name__ == "__main__":
    main()
