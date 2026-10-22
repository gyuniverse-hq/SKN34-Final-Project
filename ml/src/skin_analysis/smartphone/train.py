"""Train only three ImageNet-initialized, independent smartphone classifiers."""

import argparse
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import torch
from server.nia.metrics import classification
from torch import nn
from torch.utils.data import DataLoader
from torchvision.models import ResNet50_Weights, resnet50

from ..dataset import seed_worker
from ..runtime import capture_rng, cpu_tree, restore_rng, save_checkpoint, seed_all, select_cuda
from ..train import train_epoch
from .common import (
    DEFAULT_CONFIG,
    PREPROCESSING,
    TASKS,
    digest,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from .data import GradeDataset


class GradeModel(nn.Module):
    def __init__(self, classes, pretrained=False):
        super().__init__()
        self.network = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2 if pretrained else None)
        self.network.fc = nn.Linear(2048, classes)
        self.frozen = False

    def set_stage(self, frozen):
        self.frozen = frozen
        self.network.requires_grad_(not frozen)
        self.network.fc.requires_grad_(True)

    def train(self, mode=True):
        super().train(mode)
        if mode and self.frozen:
            self.network.eval()
            self.network.fc.train()
        return self

    def forward(self, images):
        return self.network(images)


def class_weights(labels, classes, cap):
    counts = np.bincount(labels, minlength=classes)
    if len(counts) != classes or (counts == 0).any() or not np.isfinite(cap) or cap < 1:
        raise ValueError("Every training grade and a finite weight cap >= 1 are required")
    weights = np.sqrt(len(labels) / counts)
    weights /= np.dot(weights, counts / len(labels))
    return torch.tensor(np.minimum(weights, cap), dtype=torch.float32)


def make_loader(data, settings, generator=None, training=False):
    return DataLoader(
        data,
        batch_size=settings["batch_size"],
        shuffle=training,
        num_workers=settings["num_workers"],
        pin_memory=True,
        persistent_workers=settings["num_workers"] > 0,
        worker_init_fn=seed_worker,
        generator=generator,
    )


@torch.inference_mode()
def predict(model, loader, device):
    model.eval()
    truth, predicted, probabilities = [], [], []
    total_loss = 0.0
    for images, targets, _ in loader:
        images, targets = images.to(device, non_blocking=True), targets.to(device)
        logits = model(images).float()
        total_loss += float(nn.functional.cross_entropy(logits, targets, reduction="sum"))
        truth.extend(targets.cpu().tolist())
        predicted.extend(logits.argmax(1).cpu().tolist())
        probabilities.extend(logits.softmax(1).cpu().tolist())
    return truth, predicted, probabilities, total_loss / len(truth)


def optimizer_for(model, settings, frozen):
    model.set_stage(frozen)
    groups = [
        {
            "params": model.network.fc.parameters(),
            "lr": settings["head_lr"] if frozen else settings["finetune_head_lr"],
        }
    ]
    if not frozen:
        groups.append(
            {
                "params": [
                    p for n, p in model.network.named_parameters() if not n.startswith("fc.")
                ],
                "lr": settings["backbone_lr"],
            }
        )
    optimizer = torch.optim.AdamW(groups, weight_decay=settings["weight_decay"])
    scheduler = (
        None
        if frozen
        else torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=settings["finetune_epochs"], eta_min=1e-7
        )
    )
    return optimizer, scheduler


def verify_crops(manifest):
    # Validate all audited bytes before any epoch, not just before data preparation.
    root = Path(manifest["root"])
    checked = {}
    for record in manifest["records"]:
        path = (root / record["path"]).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Crop path escapes the audited root")
        if path not in checked:
            checked[path] = file_hash(path)
        if checked[path] != record["crop_sha256"]:
            raise ValueError("Audited crop bytes have changed")


def train_task(config, manifest, task, device, resume=None):
    settings, classes = config["train"], TASKS[task]["classes"]
    output = Path(settings["output"]) / task
    if not resume and output.exists():
        raise FileExistsError("Experiment already exists; choose explicit resume or a new output")
    output.mkdir(parents=True, exist_ok=True)
    seed_all(settings["seed"])
    environment = {
        "packages": {
            p: importlib.metadata.version(p)
            for p in ("torch", "torchvision", "numpy", "pillow", "scikit-learn")
        },
        "source_hash": digest(
            {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
        ),
        "gpu": torch.cuda.get_device_name(device),
        "cuda": torch.version.cuda,
    }
    checkpoint = torch.load(resume, map_location="cpu", weights_only=True) if resume else None
    if checkpoint and (
        checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["train_config"] != settings
        or checkpoint["task"] != task
        or checkpoint["environment"] != environment
        or not (output / "best.pt").is_file()
    ):
        raise ValueError("Resume requires identical source, data, config, environment and best.pt")
    model = GradeModel(classes, pretrained=not bool(checkpoint)).to(device)
    if checkpoint:
        model.network.load_state_dict(checkpoint["model_state"], strict=True)
    initial_weights = (
        Path(torch.hub.get_dir()) / "checkpoints" / Path(ResNet50_Weights.IMAGENET1K_V2.url).name
    )
    initialization = (
        checkpoint["initialization"]
        if checkpoint
        else dict(
            source="torchvision/ResNet50_Weights.IMAGENET1K_V2",
            sha256=file_hash(initial_weights),
            nia_weights_used=False,
        )
    )
    seed_all(settings["seed"])
    generator = torch.Generator().manual_seed(settings["seed"])
    training = GradeDataset(manifest, task, "train", training=True)
    validation = GradeDataset(manifest, task, "valid")
    train_loader = make_loader(training, settings, generator, training=True)
    valid_loader = make_loader(validation, settings)
    weights = class_weights(
        [r["truth"] for r in training.records], classes, settings["class_weight_cap"]
    )
    criterion = nn.CrossEntropyLoss(weight=weights.to(device))
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    start = checkpoint["epoch"] + 1 if checkpoint else 0
    history = checkpoint["history"] if checkpoint else []
    best_key = tuple(checkpoint["best_key"]) if checkpoint else (-1.0, -float("inf"))
    stale = checkpoint["stale"] if checkpoint else 0
    frozen = start < settings["freeze_epochs"]
    optimizer, scheduler = optimizer_for(model, settings, frozen)
    if checkpoint:
        if checkpoint["stage"] == ("head" if frozen else "full_backbone"):
            optimizer.load_state_dict(checkpoint["optimizer_state"])
            if scheduler:
                scheduler.load_state_dict(checkpoint["scheduler_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        restore_rng(checkpoint["rng_state"], generator)
    total = settings["freeze_epochs"] + settings["finetune_epochs"]
    for epoch in range(start, total):
        started = time.perf_counter()
        now_frozen = epoch < settings["freeze_epochs"]
        if frozen != now_frozen:
            frozen = now_frozen
            stale = 0
            optimizer, scheduler = optimizer_for(model, settings, frozen)
        loss = train_epoch(
            model,
            train_loader,
            optimizer,
            criterion,
            device,
            scaler,
            settings["effective_batch"],
            settings["amp"],
        )
        truth, predicted, _, valid_loss = predict(model, valid_loader, device)
        metrics = classification(truth, predicted, classes)
        key = metrics["macro_f1"], -valid_loss
        improved = key > best_key
        stale = 0 if improved else stale + 1
        if improved:
            best_key = key
        if scheduler:
            scheduler.step()
        row = dict(
            task=task,
            epoch=epoch + 1,
            stage="head" if frozen else "full_backbone",
            train_loss=loss,
            valid_loss=valid_loss,
            valid_accuracy=metrics["accuracy"],
            valid_macro_f1=metrics["macro_f1"],
            valid_within_one=metrics["within_one"],
            seconds=time.perf_counter() - started,
            selected=improved,
            amp_overflow_retries=model._amp_overflow_retries,
        )
        history.append(row)
        saved = dict(
            schema="nia-smartphone-training-v1",
            architecture="resnet50",
            task=task,
            training_device="smartphone",
            resolution=256,
            grades=list(range(classes)),
            preprocessing=PREPROCESSING,
            model_state=cpu_tree(model.network.state_dict()),
            manifest_fingerprint=manifest["fingerprint"],
            train_config=settings,
            initialization=initialization,
            environment=environment,
            epoch=epoch,
            stage=row["stage"],
            history=history,
            best_key=list(best_key),
            stale=stale,
            optimizer_state=cpu_tree(optimizer.state_dict()),
            scheduler_state=scheduler.state_dict() if scheduler else None,
            scaler_state=scaler.state_dict(),
            rng_state=capture_rng(generator),
            selection="validation macro-F1; unweighted validation CE tie-break",
        )
        save_checkpoint(output / "last.pt", saved)
        if improved:
            save_checkpoint(output / "best.pt", saved)
        write_json(output / "history.json", history)
        print(json.dumps(row), flush=True)
        if not frozen and stale >= settings["patience"]:
            break
    best = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    exported = {
        k: best[k]
        for k in (
            "schema",
            "architecture",
            "task",
            "training_device",
            "resolution",
            "grades",
            "preprocessing",
            "model_state",
            "manifest_fingerprint",
            "initialization",
            "environment",
            "epoch",
            "selection",
        )
    }
    exported["kind"] = "inference"
    save_checkpoint(output / "inference.bin", exported)
    write_json(
        output / "summary.json",
        dict(
            task=task,
            best_epoch=best["epoch"] + 1,
            epochs_run=len(history),
            best_key=best["best_key"],
            sha256=file_hash(output / "inference.bin"),
        ),
    )
    del train_loader, valid_loader, optimizer, model, best, exported, saved
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", choices=[*TASKS, "all"], default="all")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    settings = config["train"]
    if (
        settings["freeze_epochs"] < 1
        or settings["finetune_epochs"] < 1
        or settings["patience"] < 1
        or settings["num_workers"] < 0
        or settings["effective_batch"] % settings["batch_size"]
    ):
        raise ValueError("Invalid training budget, loader or batch settings")
    if args.resume and args.task == "all":
        raise ValueError("Resume one explicitly selected task at a time")
    manifest = load_manifest(config)
    verify_crops(manifest)
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    for task in TASKS if args.task == "all" else [args.task]:
        train_task(config, manifest, task, device, args.resume)


if __name__ == "__main__":
    main()
