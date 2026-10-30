"""Local original-ROI regression experiment; preflight never starts training."""

# The project root supplies server.nia when the script runs outside the package.
# ruff: noqa: E402

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML_ROOT.parent))
sys.path.insert(0, str(ML_ROOT / "src"))

import numpy as np
import torch
from PIL import ImageEnhance, ImageFilter
from torch.utils.data import DataLoader
from torchvision import transforms

from skin_analysis.config import write_json
from skin_analysis.dataset import seed_worker
from skin_analysis.runtime import (
    capture_rng,
    cpu_tree,
    restore_rng,
    save_checkpoint,
    seed_all,
    select_cuda,
)
from skin_analysis.smartphone.backbones import BACKBONES, head_for
from skin_analysis.smartphone.common import file_hash, load_config, load_manifest
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.regression_study import (
    WeightedRegressionLoss,
    predictions,
    summary_metrics,
)
from skin_analysis.smartphone.sam import train_epoch as sam_train_epoch
from skin_analysis.smartphone.train import (
    GradeDiverseBatchSampler,
    GradeModel,
    class_weights,
    verify_crops,
)

BASE = Path(__file__).resolve().parent
CONFIG = ML_ROOT / "runs/pore-unsharp75-contrast40-20261028/config.toml"
DEVICE_UUID = "GPU-9ed09563-0d58-cdc7-f6bc-b2c84d8da0e3"
MODELS = ("resnet50", "efficientnet_b3", "mobilenet_v3_large")
EXPECTED_COUNTS = [114, 721, 2486, 519, 224, 48]
PIPELINE = {"radius": 1.0, "percent": 75, "threshold": 0, "contrast_factor": 1.4}
SETTINGS = {
    "seed": 42,
    "batch_size": 16,
    "effective_batch": 16,
    "train_workers": 1,
    "eval_workers": 0,
    "freeze_epochs": 1,
    "finetune_epochs": 99,
    "patience": 10,
    "head_lr": 0.001,
    "finetune_head_lr": 0.0001,
    "backbone_lr": 0.00001,
    "weight_decay": 0.0001,
    "amp": True,
    "weight_exponent": 0.5,
    "sam_rho": 0.05,
    "huber_delta": 0.2,
    "scheduler_factor": 0.5,
    "scheduler_patience": 2,
    "scheduler_threshold": 0.0001,
    "scheduler_min_lr": 1e-7,
}


class FixedPreprocessing:
    def __call__(self, image):
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=75, threshold=0))
        return ImageEnhance.Contrast(image).enhance(1.4)


class TextureDataset(GradeDataset):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transform = transforms.Compose([FixedPreprocessing(), self.transform])


def expand_rare_records(dataset):
    """Keep every original row and add deterministic replicas up to sqrt(max_count * count)."""
    original = list(dataset.records)
    by_grade = {grade: [r for r in original if r["truth"] == grade] for grade in range(6)}
    counts = [len(by_grade[g]) for g in range(6)]
    targets = [max(n, math.ceil(math.sqrt(n * max(counts)))) for n in counts]
    records = list(original)
    for grade in range(6):
        pool = list(by_grade[grade])
        random.Random(SETTINGS["seed"] + grade).shuffle(pool)
        for index in range(targets[grade] - counts[grade]):
            source = pool[index % len(pool)]
            row = dict(source)
            row["id"] = f"{source['id']}:additional:{index // len(pool) + 1}"
            records.append(row)
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Sampling replicas must have unique identities")
    dataset.records = records
    return targets


def datasets(sampling):
    config = load_config(CONFIG)
    manifest = load_manifest(config)
    configured = manifest.get("experiment_texture_preprocessing", {})
    if any(configured.get(key) != value for key, value in PIPELINE.items()):
        raise ValueError("Fixed preprocessing differs from the source experiment")
    verify_crops(manifest)
    data = TextureDataset(manifest, "pore", "train", training=True, training_seed=42)
    valid = TextureDataset(manifest, "pore", "valid")
    test = TextureDataset(manifest, "pore", "test")
    counts = [sum(r["truth"] == g for r in data.records) for g in range(6)]
    if counts != EXPECTED_COUNTS or (len(data), len(valid), len(test)) != (4112, 816, 819):
        raise ValueError(f"Unexpected fixed split or training distribution: {counts}")
    targets = expand_rare_records(data) if sampling == "sqrt_extra" else counts
    return manifest, data, valid, test, counts, targets


def loaders(data, valid, test, generator):
    sampler = GradeDiverseBatchSampler(data, SETTINGS["batch_size"], generator)
    train_loader = DataLoader(
        data,
        batch_sampler=sampler,
        num_workers=SETTINGS["train_workers"],
        pin_memory=True,
        persistent_workers=True,
        worker_init_fn=seed_worker,
        generator=torch.Generator().manual_seed(100042),
    )
    train_loader.micro_batch_size = SETTINGS["batch_size"]
    kwargs = {
        "batch_size": SETTINGS["batch_size"],
        "num_workers": SETTINGS["eval_workers"],
        "pin_memory": True,
        "shuffle": False,
    }
    return train_loader, DataLoader(valid, **kwargs), DataLoader(test, **kwargs)


RMSPROP = {"alpha": 0.99, "eps": 1e-8, "momentum": 0.0, "centered": False}


def optimizer_for(model, frozen, optimizer_name):
    model.set_stage(frozen)
    groups = [
        {
            "params": head_for(model.network).parameters(),
            "lr": SETTINGS["head_lr"] if frozen else SETTINGS["finetune_head_lr"],
        }
    ]
    if not frozen:
        groups.append(
            {
                "params": [
                    p
                    for name, p in model.network.named_parameters()
                    if not name.startswith(("fc.", "classifier.")) and p.requires_grad
                ],
                "lr": SETTINGS["backbone_lr"],
            }
        )
    if optimizer_name == "adamw":
        return torch.optim.AdamW(groups, weight_decay=SETTINGS["weight_decay"])
    if optimizer_name == "rmsprop":
        return torch.optim.RMSprop(
            groups,
            weight_decay=SETTINGS["weight_decay"],
            **RMSPROP,
        )
    raise ValueError(f"Unsupported optimizer: {optimizer_name}")


def scheduler_for(optimizer):
    return torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=SETTINGS["scheduler_factor"],
        patience=SETTINGS["scheduler_patience"],
        threshold=SETTINGS["scheduler_threshold"],
        threshold_mode="abs",
        min_lr=SETTINGS["scheduler_min_lr"],
    )


def preflight(model_name, sampling, device, optimizer_name):
    manifest, data, valid, test, counts, targets = datasets(sampling)
    batches = GradeDiverseBatchSampler(
        data, SETTINGS["batch_size"], torch.Generator().manual_seed(42)
    )
    visited = [index for batch in batches for index in batch]
    if sorted(visited) != list(range(len(data))):
        raise ValueError("Sampler did not visit every original and additional row exactly once")
    seed_all(42)
    model = GradeModel(1, pretrained=True, backbone=model_name).to(device).eval()
    train_loader, _, _ = loaders(data, valid, test, torch.Generator().manual_seed(42))
    images, labels, _ = next(iter(train_loader))
    if len(images) != SETTINGS["batch_size"] or len(labels) != SETTINGS["batch_size"]:
        raise ValueError("Data loader did not produce the configured batch")
    with torch.inference_mode(), torch.amp.autocast("cuda", enabled=True):
        result = model(images.to(device))
    if result.shape != (SETTINGS["batch_size"], 1) or not torch.isfinite(result).all():
        raise ValueError("Invalid model output")
    optimizer_for(model, True, optimizer_name)
    optimizer = optimizer_for(model, False, optimizer_name)
    head_ids = {id(p) for p in head_for(model.network).parameters()}
    groups = [{id(p) for p in group["params"]} for group in optimizer.param_groups]
    expected_ids = {id(p) for p in model.parameters() if p.requires_grad}
    if groups[0] != head_ids or groups[0] & groups[1] or set.union(*groups) != expected_ids:
        raise ValueError("Head and backbone optimizer groups do not match model parameters")
    print(
        json.dumps(
            {
                "model": model_name,
                "device": torch.cuda.get_device_name(0),
                "train_original": 4112,
                "valid": len(valid),
                "test": len(test),
                "sampling": sampling,
                "optimizer": optimizer_name,
                "draws_per_epoch": len(data),
                "original_grade_counts": counts,
                "draws_by_grade": targets,
                "updates_per_epoch": math.ceil(len(data) / SETTINGS["effective_batch"]),
                "output_shape": list(result.shape),
                "pretrained_weights": str(BACKBONES[model_name][1]),
                "sampler_all_rows_once": True,
                "source_manifest_fingerprint": manifest["fingerprint"],
                "source_cache_sha256": manifest["pixel_cache"]["sha256"],
                "note": "one batch of inference only; training memory is not verified",
            }
        ),
        flush=True,
    )


def train(model_name, sampling, device, resume, optimizer_name):
    manifest, data, valid, test, counts, targets = datasets(sampling)
    run_name = sampling if optimizer_name == "adamw" else f"{sampling}_{optimizer_name}"
    output = BASE / "results" / model_name / run_name
    last_path = output / "last.pt"
    if output.exists() and any(output.iterdir()) and not resume:
        raise FileExistsError("Experiment output already exists; use --resume")
    if resume and not last_path.exists():
        raise FileNotFoundError("No checkpoint to resume")
    output.mkdir(parents=True, exist_ok=True)
    state = torch.load(last_path, map_location="cpu", weights_only=True) if resume else None
    contract = {
        "model": model_name,
        "sampling": sampling,
        "optimizer": {
            "name": optimizer_name,
            "parameters": RMSPROP if optimizer_name == "rmsprop" else {"weight_decay": SETTINGS["weight_decay"]},
            "base_optimizer_in_sam": optimizer_name,
            "sam_rho": SETTINGS["sam_rho"],
        },
        "settings": SETTINGS,
        "pipeline": PIPELINE,
        "manifest_fingerprint": manifest["fingerprint"],
        "source_cache_sha256": manifest["pixel_cache"]["sha256"],
        "pretrained_weights": str(BACKBONES[model_name][1]),
        "script_sha256": file_hash(__file__),
        "backbone_source_sha256": file_hash(ML_ROOT / "src/skin_analysis/smartphone/backbones.py"),
        "sampler_source_sha256": file_hash(ML_ROOT / "src/skin_analysis/smartphone/train.py"),
    }
    if state and state["contract"] != contract:
        raise ValueError("Resume checkpoint model, data or settings differ")
    if state and not state["frozen"] and state["stale"] >= SETTINGS["patience"]:
        raise ValueError("This experiment already reached early stopping")
    seed_all(42)
    model = GradeModel(1, pretrained=not resume, backbone=model_name).to(device)
    if state:
        model.network.load_state_dict(state["model_state"])
    seed_all(42)
    generator = torch.Generator().manual_seed(42)
    train_loader, valid_loader, test_loader = loaders(data, valid, test, generator)
    labels = [
        record["truth"]
        for record in manifest["records"]
        if record["task"] == "pore" and record["split"] == "train"
    ]
    weights = class_weights(labels, 6, None, exponent=SETTINGS["weight_exponent"])
    criterion = WeightedRegressionLoss(weights.to(device), "huber", delta=SETTINGS["huber_delta"])
    scaler = torch.amp.GradScaler("cuda", enabled=SETTINGS["amp"])
    start = state["epoch"] if state else 0
    history = state["history"] if state else []
    best = tuple(state["best_key"]) if state else (-float("inf"), -float("inf"))
    stale = state["stale"] if state else 0
    frozen = start < SETTINGS["freeze_epochs"]
    optimizer = optimizer_for(model, frozen, optimizer_name)
    scheduler = None if frozen else scheduler_for(optimizer)
    if state:
        if state["frozen"] == frozen:
            optimizer.load_state_dict(state["optimizer_state"])
            if scheduler is not None:
                scheduler.load_state_dict(state["scheduler_state"])
        else:
            stale = 0
        scaler.load_state_dict(state["scaler_state"])
        restore_rng(state["rng_state"], generator)
    for index in range(start, SETTINGS["freeze_epochs"] + SETTINGS["finetune_epochs"]):
        is_frozen = index < SETTINGS["freeze_epochs"]
        if frozen != is_frozen:
            frozen = is_frozen
            optimizer = optimizer_for(model, frozen, optimizer_name)
            scheduler = None if frozen else scheduler_for(optimizer)
            stale = 0
        data.set_epoch(index)
        started = time.perf_counter()
        train_loss = sam_train_epoch(
            model,
            train_loader,
            optimizer,
            criterion,
            device,
            scaler,
            SETTINGS["effective_batch"],
            SETTINGS["amp"],
            rho=SETTINGS["sam_rho"],
        )
        truth, scores = predictions(model, valid_loader, device)
        metrics = summary_metrics(truth, scores)
        key = (metrics["macro_f1"], -metrics["mse"])
        improved = key > best
        if improved:
            best, stale = key, 0
        elif not frozen:
            stale += 1
        if scheduler:
            scheduler.step(metrics["macro_f1"])
        row = {
            "epoch": index + 1,
            "stage": "head" if frozen else "full_backbone",
            "train_loss": train_loss,
            "valid_macro_f1": metrics["macro_f1"],
            "valid_mse": metrics["mse"],
            "valid_accuracy": metrics["accuracy"],
            "valid_within_one": metrics["within_one"],
            "valid_per_grade": metrics["per_grade"],
            "selected": improved,
            "stale_epochs": stale,
            "lr": [g["lr"] for g in optimizer.param_groups],
            "samples_seen": len(data),
            "sam_steps": model._sam_steps,
            "seconds": round(time.perf_counter() - started, 2),
        }
        if model._sam_steps != math.ceil(len(data) / SETTINGS["effective_batch"]):
            raise RuntimeError("Unexpected number of SAM updates")
        history.append(row)
        checkpoint = {
            "schema": "pore-local-backbone-regression-v1",
            "contract": contract,
            "epoch": index + 1,
            "frozen": frozen,
            "model_state": cpu_tree(model.network.state_dict()),
            "optimizer_state": cpu_tree(optimizer.state_dict()),
            "scheduler_state": scheduler.state_dict() if scheduler else None,
            "scaler_state": scaler.state_dict(),
            "rng_state": capture_rng(generator),
            "best_key": list(best),
            "stale": stale,
            "history": history,
            "class_weights": weights.tolist(),
            "original_grade_counts": counts,
            "samples_by_grade": targets,
        }
        save_checkpoint(last_path, checkpoint)
        if improved:
            save_checkpoint(output / "best.pt", checkpoint)
        write_json(output / "history.json", history)
        print(json.dumps(row), flush=True)
        if not frozen and stale >= SETTINGS["patience"]:
            break
    chosen = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    model.network.load_state_dict(chosen["model_state"])
    truth, scores = predictions(model, test_loader, device)
    metrics = summary_metrics(truth, scores)
    write_json(
        output / "test-predictions.json",
        [
            {
                "id": record["id"],
                "group": record["group"],
                "truth": int(actual),
                "score": float(score),
                "predicted": int(np.clip(np.floor(score + 0.5), 0, 5)),
            }
            for record, actual, score in zip(test.records, truth, scores, strict=True)
        ],
    )
    write_json(
        output / "summary.json",
        {
            "contract": contract,
            "epochs_run": len(history),
            "best_epoch": chosen["epoch"],
            "best_validation_macro_f1": best[0],
            "best_validation_mse": -best[1],
            "test_metrics": metrics,
            "class_weights": weights.tolist(),
            "samples_by_grade": targets,
        },
    )
    print(
        json.dumps(
            {"completed": True, "best_epoch": chosen["epoch"], "test_macro_f1": metrics["macro_f1"]}
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["preflight", "train"])
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--sampling", choices=["all_once", "sqrt_extra"], required=True)
    parser.add_argument("--optimizer", choices=["adamw", "rmsprop"], default="adamw")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.action == "preflight" and args.resume:
        parser.error("--resume is only for training")
    os.chdir(ML_ROOT)
    device = select_cuda(DEVICE_UUID)
    torch.set_num_threads(4)
    if args.action == "preflight":
        preflight(args.model, args.sampling, device, args.optimizer)
    else:
        train(args.model, args.sampling, device, args.resume, args.optimizer)


if __name__ == "__main__":
    main()
