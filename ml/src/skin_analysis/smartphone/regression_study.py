"""Compare weighted Huber and MSE on bounded smartphone pore-grade regression."""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from server.nia.metrics import classification
from torch import nn

from ..runtime import cpu_tree, save_checkpoint, seed_all, select_cuda
from ..train import train_epoch as adamw_train_epoch
from .common import load_config, load_manifest, write_json
from .data import GradeDataset
from .sam import train_epoch as sam_train_epoch
from .train import GradeModel, class_weights, make_loader, optimizer_for, verify_crops


class WeightedRegressionLoss(nn.Module):
    def __init__(self, weights, kind, delta=0.2):
        super().__init__()
        if kind not in ("huber", "mse") or delta <= 0:
            raise ValueError("Invalid regression loss")
        self.register_buffer("weights", weights)
        self.kind, self.delta = kind, delta

    def forward(self, logits, labels):
        prediction = torch.sigmoid(logits.float().reshape(-1))
        target = labels.float() / 5.0
        losses = (
            F.huber_loss(prediction, target, delta=self.delta, reduction="none")
            if self.kind == "huber"
            else (prediction - target).square()
        )
        weights = self.weights[labels.long()]
        return (losses * weights).sum() / weights.sum()


@torch.inference_mode()
def predictions(model, loader, device):
    model.eval()
    truth, scores = [], []
    for images, labels, _ in loader:
        logits = model(images.to(device, non_blocking=True)).float().reshape(-1)
        scores.extend((5.0 * torch.sigmoid(logits)).cpu().tolist())
        truth.extend(labels.tolist())
    return truth, scores


def discrete(scores):
    return np.clip(np.floor(np.asarray(scores, dtype=np.float64) + 0.5), 0, 5).astype(int).tolist()


def summary_metrics(truth, scores):
    y = np.asarray(truth, dtype=np.float64)
    p = np.asarray(scores, dtype=np.float64)
    if len(y) == 0 or not np.isfinite(p).all() or (p < 0).any() or (p > 5).any():
        raise ValueError("Invalid predictions")
    result = classification(list(map(int, truth)), discrete(scores), 6)
    result.update(
        mse=float(np.mean((p - y) ** 2)),
        rmse=float(np.sqrt(np.mean((p - y) ** 2))),
        continuous_mae=float(np.mean(np.abs(p - y))),
    )
    result["micro_f1"] = result["accuracy"]
    result["mean_prediction_by_grade"] = [
        float(p[y == grade].mean()) if np.any(y == grade) else None for grade in range(6)
    ]
    return result


def train(config, manifest, kind, output, device, optimizer_kind):
    settings = config["train"]
    settings["optimizer"] = optimizer_kind
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seed_all(settings["seed"])
    model = GradeModel(1, pretrained=True, backbone="resnet50").to(device)
    seed_all(settings["seed"])
    generator = torch.Generator().manual_seed(settings["seed"])
    repeat_augmentation = {
        int(grade): settings["repeat_augmentation"]
        for grade in settings.get("repeat_augmentation_grades", [])
    }
    training = GradeDataset(
        manifest,
        "pore",
        "train",
        training=True,
        training_seed=settings["seed"],
        repeat_augmentation_by_grade=repeat_augmentation,
    )
    validation = GradeDataset(manifest, "pore", "valid")
    train_loader = make_loader(training, settings, generator, training=True)
    valid_loader = make_loader(validation, settings)
    weights = class_weights(
        [r["truth"] for r in training.records],
        6,
        None,
        exponent=settings.get("weight_exponent", 0.5),
    )
    loss = WeightedRegressionLoss(weights.to(device), kind, delta=0.2)
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    optimizer, scheduler = optimizer_for(model, settings, frozen=True)
    best = (-float("inf"), -float("inf"))
    history = []
    stale = 0
    start = time.perf_counter()
    for epoch in range(settings["freeze_epochs"] + settings["finetune_epochs"]):
        training.set_epoch(epoch)
        frozen = epoch < settings["freeze_epochs"]
        if epoch == settings["freeze_epochs"]:
            optimizer, scheduler = optimizer_for(model, settings, frozen=False)
            stale = 0
        epoch_start = time.perf_counter()
        if optimizer_kind == "sam_adamw":
            train_loss = sam_train_epoch(
                model,
                train_loader,
                optimizer,
                loss,
                device,
                scaler,
                settings["effective_batch"],
                settings["amp"],
                rho=settings["sam_rho"],
            )
            sam_steps = model._sam_steps
        else:
            train_loss = adamw_train_epoch(
                model,
                train_loader,
                optimizer,
                loss,
                device,
                scaler,
                settings["effective_batch"],
                settings["amp"],
            )
            sam_steps = 0
        truth, scores = predictions(model, valid_loader, device)
        metrics = summary_metrics(truth, scores)
        key = (metrics["macro_f1"], -metrics["mse"])
        improved = key > best
        if improved:
            best, stale = key, 0
        else:
            stale += 1
        if scheduler:
            scheduler.step()
        row = {
            "epoch": epoch + 1,
            "stage": "head" if frozen else "full_backbone",
            "train_loss": train_loss,
            "valid_mse": metrics["mse"],
            "valid_macro_f1": metrics["macro_f1"],
            "valid_accuracy": metrics["accuracy"],
            "valid_within_one": metrics["within_one"],
            "selected": improved,
            "optimizer": optimizer_kind,
            "sam_steps": sam_steps,
            "amp_overflow_retries": model._amp_overflow_retries,
            "seconds": time.perf_counter() - epoch_start,
        }
        history.append(row)
        checkpoint = {
            "schema": "pore-bounded-grade-regression-v1",
            "kind": kind,
            "optimizer": optimizer_kind,
            "model_state": cpu_tree(model.network.state_dict()),
            "manifest_fingerprint": manifest["fingerprint"],
            "epoch": epoch + 1,
            "settings": settings,
            "weights": weights.tolist(),
            "huber_delta": 0.2 if kind == "huber" else None,
            "normalization": "target/5; sigmoid output times 5",
            "rounding": "floor(score+0.5), clamp to 0..5",
            "history": history,
        }
        save_checkpoint(output / "last.pt", checkpoint)
        if improved:
            save_checkpoint(output / "best.pt", checkpoint)
        write_json(output / "history.json", history)
        print(json.dumps({"kind": kind, **row}), flush=True)
        if not frozen and stale >= settings["patience"]:
            break
    write_json(
        output / "summary.json",
        {
            "kind": kind,
            "optimizer": optimizer_kind,
            "epochs_run": len(history),
            "best_epoch": torch.load(output / "best.pt", map_location="cpu", weights_only=True)[
                "epoch"
            ],
            "best_validation_macro_f1": best[0],
            "best_validation_mse": -best[1],
            "weights": weights.tolist(),
            "wall_seconds": time.perf_counter() - start,
        },
    )
    del model, train_loader, valid_loader, optimizer
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--loss", choices=["huber", "mse"], required=True)
    parser.add_argument("--optimizer", choices=["sam_adamw", "adamw"], default="sam_adamw")
    args = parser.parse_args()
    config = load_config(args.config)
    assert config["train"]["freeze_epochs"] == 2 and config["train"]["finetune_epochs"] == 18
    assert config["train"]["batch_size"] == config["train"]["effective_batch"] == 16
    assert config["train"]["seed"] == 42 and config["train"]["grade_diverse_batches"]
    manifest = load_manifest(config)
    verify_crops(manifest)
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    train(config, manifest, args.loss, args.output, device, args.optimizer)


if __name__ == "__main__":
    main()
