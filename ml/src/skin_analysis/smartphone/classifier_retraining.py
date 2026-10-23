"""Validation-only, frozen-backbone classifier retraining for pore grades.

This is a cRT-inspired adaptation using the existing WCE+SAM representation,
ordinary CE, balanced sampling and head-only AdamW+SAM, not a paper reproduction.
"""

import argparse
import importlib.metadata
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, Sampler

from ..config import PROJECT_ROOT
from ..dataset import seed_worker
from ..runtime import capture_rng, cpu_tree, save_checkpoint, seed_all, select_cuda
from .common import PREPROCESSING, digest, file_hash, load_config, load_manifest, write_json
from .data import GradeDataset
from .focal_compare import qualifies, verified_metrics
from .sam import train_epoch
from .train import GradeModel, make_loader, predict, verify_crops

BASELINE = PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42/pore/inference.bin"
BASELINE_SHA = "18c5ddd6c921c22a1bf55010a437e32f682470cfce41a9d6a7d2295f75e77644"
SIX_ROOT = PROJECT_ROOT / "runs/nia-smartphone-classifier-retraining-seed-42"
SCHEMA = "nia-classifier-retraining-v1"


def label_mapping(classes):
    if classes not in (3, 6):
        raise ValueError("Only original six or explicitly paired three classes are supported")
    return [g if classes == 6 else g // 2 for g in range(6)]


class TargetDataset(Dataset):
    """Derive training targets without mutating audited source records or labels."""

    def __init__(self, base, classes):
        self.base = base
        self.mapping = label_mapping(classes)

    def __len__(self):
        return len(self.base)

    def __getitem__(self, index):
        image, target, index = self.base[index]
        return image, torch.tensor(self.mapping[int(target)], dtype=torch.long), index


class BalancedSubjectSampler(Sampler):
    """Exactly N draws: balanced target, uniform person, uniform ROI, replacement.

    Each epoch has the original N training ROIs' step budget. Repeated draws do
    not add subjects. Validation/test records can never enter this sampler.
    """

    def __init__(self, records, classes, generator):
        mapping = label_mapping(classes)
        groups = defaultdict(lambda: defaultdict(list))
        for i, record in enumerate(records):
            truth = record["truth"]
            if (
                record["split"] != "train"
                or record["task"] != "pore"
                or type(truth) is not int
                or not 0 <= truth < 6
            ):
                raise ValueError("Sampler accepts only audited pore training labels 0..5")
            groups[mapping[truth]][record["subject"]].append(i)
        if set(groups) != set(range(classes)):
            raise ValueError("Every target class requires training subjects")
        self.groups = [[indices for indices in groups[g].values()] for g in range(classes)]
        self.count, self.classes, self.generator = len(records), classes, generator

    def __len__(self):
        return self.count

    def __iter__(self):
        # Rotate the remainder classes randomly; counts differ by at most one.
        order = torch.randperm(self.classes, generator=self.generator)
        labels = order[torch.arange(self.count) % self.classes]
        labels = labels[torch.randperm(self.count, generator=self.generator)]
        for grade in labels.tolist():
            people = self.groups[grade]
            person = people[int(torch.randint(len(people), (), generator=self.generator))]
            yield person[int(torch.randint(len(person), (), generator=self.generator))]


def frozen_backbone_matches(state, source):
    return state.keys() == source.keys() and all(
        torch.equal(value.cpu(), source[name])
        for name, value in state.items()
        if not name.startswith("fc.")
    )


def initialize_classifier(source, classes, seed):
    model = GradeModel(6)
    model.network.load_state_dict(source, strict=True)
    # Same deterministic new-head initialization, independent of backbone setup.
    torch.manual_seed(seed)
    model.network.fc = nn.Linear(2048, classes)
    model.set_stage(True)
    model.train()
    if not frozen_backbone_matches(model.network.state_dict(), source):
        raise ValueError("Backbone changed during classifier initialization")
    return model


def load_candidate(checkpoint, classes):
    """Require the target contract; never silently treat coarse labels as 0..5."""
    if (
        checkpoint.get("schema") != SCHEMA
        or checkpoint.get("architecture") != "resnet50"
        or checkpoint.get("task") != ("pore" if classes == 6 else "pore_coarse")
        or checkpoint.get("grades") != list(range(classes))
        or checkpoint.get("original_to_target") != label_mapping(classes)
        or checkpoint.get("preprocessing") != PREPROCESSING
        or checkpoint.get("decoding") != "softmax_argmax"
        or checkpoint.get("initialization", {}).get("sha256") != BASELINE_SHA
    ):
        raise ValueError("Incompatible classifier target/provenance contract")
    if not all(torch.isfinite(v).all() for v in checkpoint["model_state"].values()):
        raise ValueError("Non-finite checkpoint")
    model = GradeModel(classes)
    model.network.load_state_dict(checkpoint["model_state"], strict=True)
    model.set_stage(True)
    return model.eval()


def coarse_probabilities(probabilities):
    values = np.asarray(probabilities, dtype=float)
    if (
        values.ndim != 2
        or values.shape[1] != 6
        or not np.isfinite(values).all()
        or (values < 0).any()
        or not np.allclose(values.sum(1), 1)
    ):
        raise ValueError("Expected six-class normalized probabilities")
    return values.reshape(-1, 3, 2).sum(2)


def metrics_for(truth, predicted, classes):
    metrics = verified_metrics(truth, predicted, classes)
    if classes == 3:
        # The old helper pools the last TWO grades; here only target 2 is high.
        metrics["high_grade_pooled_recall"] = metrics["per_grade"][2]["recall"]
    return metrics


def passes_six_gate(baseline, candidate):
    return qualifies(baseline, candidate) and candidate["per_grade"][5]["recall"] > 0


def preflight(config):
    settings = config["train"]
    classes = settings["classes"]
    label_mapping(classes)
    if (
        settings["epochs"] < 1
        or settings["patience"] < 1
        or settings["effective_batch"] != settings["batch_size"]
        or settings["num_workers"] < 0
        or settings["loss"] != "unweighted_cross_entropy"
        or settings["optimizer"] != "sam_adamw"
    ):
        raise ValueError("Invalid classifier-retraining settings")
    if file_hash(BASELINE) != BASELINE_SHA:
        raise ValueError("The preserved WCE+SAM baseline has changed")
    source = torch.load(BASELINE, map_location="cpu", weights_only=True)
    manifest = load_manifest(config)
    if (
        source["task"] != "pore"
        or source["grades"] != list(range(6))
        or source["manifest_fingerprint"] != manifest["fingerprint"]
        or source["preprocessing"] != PREPROCESSING
    ):
        raise ValueError("Baseline/data contract mismatch")
    if classes == 3:
        decision = json.loads((SIX_ROOT / "comparison.json").read_text(encoding="utf-8"))
        six = decision["results"]
        if (
            decision["manifest_fingerprint"] != manifest["fingerprint"]
            or decision["test_set_evaluated"] is not False
            or decision["passes_gate"] is not False
            or passes_six_gate(six["baseline"]["valid"], six["candidate"]["valid"])
        ):
            raise ValueError("Three-class fallback requires a recorded failed six-class gate")
    return source, manifest


def preservation(config):
    path = Path(config["train"]["output"]) / "preservation-before.json"
    if path.exists():
        before = json.loads(path.read_text(encoding="utf-8"))
    else:
        previous = PROJECT_ROOT / "runs/nia-smartphone-weighted-focal-sam-seed-42"
        before = json.loads((previous / "preservation-before.json").read_text(encoding="utf-8"))
        weight = previous / "pore/inference.bin"
        before[str(weight.relative_to(PROJECT_ROOT.parent))] = file_hash(weight)
        if config["train"]["classes"] == 3:
            weight = SIX_ROOT / "pore/inference.bin"
            before[str(weight.relative_to(PROJECT_ROOT.parent))] = file_hash(weight)
    if before != {p: file_hash(PROJECT_ROOT.parent / p) for p in before}:
        raise ValueError("Preserved model or service configuration changed")
    if not path.exists():
        write_json(path, before)
    return len(before)


def train(config):
    source, manifest = preflight(config)
    preservation(config)
    settings, started = config["train"], time.perf_counter()
    classes = settings["classes"]
    output = Path(settings["output"]) / "pore"
    if output.exists():
        raise FileExistsError("Use a new output; completed/partial runs are never overwritten")
    verify_crops(manifest)
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    seed_all(settings["seed"])
    model = initialize_classifier(source["model_state"], classes, settings["seed"]).to(device)
    generator = torch.Generator().manual_seed(settings["seed"])
    base = GradeDataset(manifest, "pore", "train", training=True)
    sampler = BalancedSubjectSampler(base.records, classes, generator)
    loader = DataLoader(
        TargetDataset(base, classes),
        sampler=sampler,
        batch_size=settings["batch_size"],
        num_workers=settings["num_workers"],
        pin_memory=True,
        persistent_workers=settings["num_workers"] > 0,
        generator=generator,
        worker_init_fn=seed_worker,
    )
    valid_loader = make_loader(
        TargetDataset(GradeDataset(manifest, "pore", "valid"), classes),
        settings,
        torch.Generator().manual_seed(settings["seed"] + 1),
    )
    optimizer = torch.optim.AdamW(
        model.network.fc.parameters(),
        lr=settings["head_lr"],
        weight_decay=settings["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=settings["epochs"],
        eta_min=1e-7,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    history, best_key, stale = [], (-1.0, -float("inf")), 0
    environment = dict(
        packages={p: importlib.metadata.version(p) for p in source["environment"]["packages"]},
        gpu=torch.cuda.get_device_name(device),
        cuda=torch.version.cuda,
        source_hash=digest({p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")}),
    )
    for epoch in range(settings["epochs"]):
        tick = time.perf_counter()
        loss = train_epoch(
            model,
            loader,
            optimizer,
            nn.CrossEntropyLoss(),
            device,
            scaler,
            settings["effective_batch"],
            settings["amp"],
            rho=settings["sam_rho"],
        )
        truth, predicted, _, valid_loss = predict(model, valid_loader, device)
        metrics = metrics_for(truth, predicted, classes)
        key = metrics["macro_f1"], -valid_loss
        improved = key > best_key
        stale = 0 if improved else stale + 1
        best_key = max(key, best_key)
        scheduler.step()
        state = cpu_tree(model.network.state_dict())
        if not frozen_backbone_matches(state, source["model_state"]):
            raise ValueError("A frozen backbone parameter or BN buffer changed")
        row = dict(
            epoch=epoch + 1,
            train_loss=loss,
            valid_loss=valid_loss,
            valid_accuracy=metrics["accuracy"],
            valid_macro_f1=metrics["macro_f1"],
            valid_high_recall=metrics["high_grade_pooled_recall"],
            valid_last_grade_recall=metrics["per_grade"][-1]["recall"],
            selected=improved,
            seconds=time.perf_counter() - tick,
            sam_steps=model._sam_steps,
            amp_overflow_retries=model._amp_overflow_retries,
            trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
        )
        history.append(row)
        saved = dict(
            schema=SCHEMA,
            architecture="resnet50",
            decoding="softmax_argmax",
            task="pore" if classes == 6 else "pore_coarse",
            training_device="smartphone",
            grades=list(range(classes)),
            original_grades=list(range(6)),
            original_to_target=label_mapping(classes),
            resolution=256,
            preprocessing=PREPROCESSING,
            manifest_fingerprint=manifest["fingerprint"],
            initialization=dict(source="trained_wce_sam_backbone", sha256=BASELINE_SHA),
            model_state=state,
            train_config=settings,
            environment=environment,
            epoch=epoch,
            history=history,
            best_key=list(best_key),
            stale=stale,
            selection="validation macro-F1; unweighted CE tie-break",
            loss_spec=dict(kind="unweighted_cross_entropy", class_weights_used=False),
            sampling="balanced_target_uniform_subject_uniform_roi_with_replacement",
            frozen_backbone_including_bn_verified=True,
            optimizer_state=cpu_tree(optimizer.state_dict()),
            scheduler_state=scheduler.state_dict(),
            scaler_state=scaler.state_dict(),
            rng_state=capture_rng(generator),
        )
        save_checkpoint(output / "last.pt", saved)
        if improved:
            save_checkpoint(output / "best.pt", saved)
        write_json(output / "history.json", history)
        print(json.dumps(row), flush=True)
        if stale >= settings["patience"]:
            break
    best = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    exported = {
        k: v
        for k, v in best.items()
        if k
        not in {
            "optimizer_state",
            "scheduler_state",
            "scaler_state",
            "rng_state",
            "history",
        }
    }
    exported["kind"] = "inference"
    load_candidate(exported, classes)
    save_checkpoint(output / "inference.bin", exported)
    write_json(
        output / "summary.json",
        dict(
            best_epoch=best["epoch"] + 1,
            epochs_run=len(history),
            seconds=time.perf_counter() - started,
            sha256=file_hash(output / "inference.bin"),
            backbone_unchanged=True,
            classes=classes,
        ),
    )
    preservation(config)


def evaluate(config):
    source, manifest = preflight(config)
    preservation(config)
    settings = config["train"]
    classes, root = settings["classes"], Path(settings["output"])
    if (root / "comparison.json").exists():
        raise FileExistsError("Comparison already recorded")
    verify_crops(manifest)
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    data = {s: GradeDataset(manifest, "pore", s) for s in ("train", "valid")}
    checkpoint = torch.load(root / "pore/inference.bin", map_location="cpu", weights_only=True)
    if (
        checkpoint["train_config"] != settings
        or checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or not frozen_backbone_matches(checkpoint["model_state"], source["model_state"])
    ):
        raise ValueError("Candidate config, data or frozen backbone mismatch")
    summary = json.loads((root / "pore/summary.json").read_text(encoding="utf-8"))
    if file_hash(root / "pore/inference.bin") != summary["sha256"]:
        raise ValueError("Candidate hash mismatch")
    candidate = load_candidate(checkpoint, classes).to(device)
    baseline = GradeModel(6).to(device)
    baseline.network.load_state_dict(source["model_state"], strict=True)
    results = {}
    for name, model in (("baseline", baseline), ("candidate", candidate)):
        rows = {}
        for split, base in data.items():
            dataset = base if name == "baseline" else TargetDataset(base, classes)
            loader = make_loader(dataset, settings)
            truth, predicted, probabilities, loss = predict(model, loader, device)
            if name == "baseline" and classes == 3:
                probabilities = coarse_probabilities(probabilities).tolist()
                truth = [g // 2 for g in truth]
                predicted = np.argmax(probabilities, axis=1).tolist()
                loss = float(
                    -np.log(
                        np.maximum(
                            np.asarray(probabilities)[np.arange(len(truth)), truth],
                            1e-30,
                        )
                    ).mean()
                )
            rows[split] = metrics_for(truth, predicted, classes)
            rows[split]["unweighted_ce"] = loss
            write_json(
                root / f"{name}-{split}-predictions.json",
                dict(
                    original_truth=[r["truth"] for r in base.records],
                    truth=truth,
                    predicted=predicted,
                    probabilities=probabilities,
                    subjects=[r["subject"] for r in base.records],
                ),
            )
        results[name] = rows
    b, c = results["baseline"]["valid"], results["candidate"]["valid"]
    passed = (
        passes_six_gate(b, c)
        if classes == 6
        else (
            c["macro_f1"] > b["macro_f1"]
            and c["accuracy"] >= b["accuracy"]
            and c["high_grade_pooled_recall"] > b["high_grade_pooled_recall"]
        )
    )
    write_json(
        root / "comparison.json",
        dict(
            schema=SCHEMA,
            manifest_fingerprint=manifest["fingerprint"],
            classes=classes,
            original_to_target=label_mapping(classes),
            test_set_evaluated=False,
            passes_gate=passed,
            results=results,
            summary=summary,
            baseline_sha256=BASELINE_SHA,
            candidate_sha256=summary["sha256"],
            frozen_backbone_including_bn_verified=True,
            selection="validation macro-F1; unweighted CE tie-break",
            gate="macro-F1 increases; accuracy does not decrease; high-grade recall increases"
            + ("; grade-5 recall > 0" if classes == 6 else ""),
            baseline_decoding="sum paired six-class probabilities then argmax"
            if classes == 3
            else "six-class argmax",
        ),
    )
    preservation(config)
    print(
        json.dumps(dict(classes=classes, passes_gate=passed, baseline=b, candidate=c)), flush=True
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--phase", choices=("preflight", "train", "evaluate"), required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.phase == "preflight":
        preflight(config)
        print(json.dumps(dict(preflight="passed", preserved_files=preservation(config))))
    elif args.phase == "train":
        train(config)
    else:
        evaluate(config)


if __name__ == "__main__":
    main()
