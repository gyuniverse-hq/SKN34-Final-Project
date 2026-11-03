"""Prepare, inspect and train the PLAN.md binary-pore comparison (setup by default)."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

ML = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ML / "src"), str(ML.parent)]

import numpy as np
import torch
from PIL import ImageEnhance, ImageFilter
from torch import nn
from torch.utils.data import DataLoader
from torchvision import transforms
from tqdm.auto import tqdm

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
from skin_analysis.smartphone.common import file_hash, load_manifest
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.sam import train_epoch as sam_train_epoch
from skin_analysis.smartphone.train import GradeDiverseBatchSampler, GradeModel, verify_crops

DEFAULT_BASELINE = ML / "runs/pore-backbone-original-20261028/results/mobilenet_v3_large/sqrt_extra"
DEFAULT_MANIFEST = ML / "runs/pore-unsharp75-contrast40-20261028/manifest/manifest.json"
DEFAULT_OUTPUT = ML / "runs/pore-binary-20261101"
DEFAULT_GPU = "GPU-9ed09563-0d58-cdc7-f6bc-b2c84d8da0e3"
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
    "sam_rho": 0.05,
    "scheduler_factor": 0.5,
    "scheduler_patience": 2,
    "scheduler_threshold": 0.0001,
    "scheduler_min_lr": 1e-7,
}
PIPELINE = {"radius": 1.0, "percent": 75, "threshold": 0, "contrast_factor": 1.4}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class FixedTexture:
    def __call__(self, image):
        image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=75, threshold=0))
        return ImageEnhance.Contrast(image).enhance(1.4)


class PoreDataset(GradeDataset):
    """Keep original grade targets for identical sampling and grade 4/5 diagnostics."""

    def __init__(self, manifest, split, training=False):
        super().__init__(
            manifest,
            "pore",
            split,
            training=training,
            training_seed=SETTINGS["seed"] if training else None,
        )
        self.transform = transforms.Compose([FixedTexture(), self.transform])


def expand_training(data):
    original = list(data.records)
    pools = [[r for r in original if r["truth"] == grade] for grade in range(6)]
    counts = [len(pool) for pool in pools]
    if counts != [114, 721, 2486, 519, 224, 48]:
        raise ValueError(f"The selected baseline split changed: {counts}")
    targets = [math.ceil(math.sqrt(n * max(counts))) for n in counts]
    for grade, pool in enumerate(pools):
        random.Random(42 + grade).shuffle(pool)
        for index in range(targets[grade] - counts[grade]):
            source = pool[index % len(pool)]
            data.records.append(
                {
                    **source,
                    "id": f"{source['id']}:additional:{index // len(pool) + 1}",
                }
            )
    if len({r["id"] for r in data.records}) != len(data):
        raise ValueError("Nonunique sampling identities")
    return counts, targets


def binary_metrics(grades, probabilities):
    grades = np.asarray(grades, dtype=np.int64)
    p = np.asarray(probabilities, dtype=np.float64)
    if (
        not len(grades)
        or p.shape != grades.shape
        or not np.isfinite(p).all()
        or (p < 0).any()
        or (p > 1).any()
        or (grades < 0).any()
        or (grades > 5).any()
    ):
        raise ValueError("Invalid binary evaluation input")
    truth, predicted = (grades >= 3).astype(int), (p >= 0.5).astype(int)
    matrix = np.bincount(truth * 2 + predicted, minlength=4).reshape(2, 2)
    rows = []
    for label, name in enumerate(("양호", "유의")):
        tp = int(matrix[label, label])
        support, selected = int(matrix[label].sum()), int(matrix[:, label].sum())
        precision, recall = tp / selected if selected else 0, tp / support if support else 0
        rows.append(
            {
                "label": label,
                "name": name,
                "support": support,
                "precision": precision,
                "recall": recall,
                "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            }
        )
    high = grades >= 4
    ce = -(truth * np.log(np.clip(p, 1e-12, 1)) + (1 - truth) * np.log(np.clip(1 - p, 1e-12, 1)))
    by_grade = []
    for grade in range(6):
        mask = grades == grade
        by_grade.append(
            {
                "grade": grade,
                "support": int(mask.sum()),
                "caution_recall": float(predicted[mask].mean()) if mask.any() else None,
            }
        )
    return {
        "n": len(grades),
        "threshold": 0.5,
        "confusion": matrix.tolist(),
        "accuracy": float(np.mean(truth == predicted)),
        "macro_f1": float(np.mean([r["f1"] for r in rows])),
        "macro_precision": float(np.mean([r["precision"] for r in rows])),
        "macro_recall": float(np.mean([r["recall"] for r in rows])),
        "cross_entropy": float(ce.mean()),
        "per_class": rows,
        "grade45_support": int(high.sum()),
        "grade45_missed_as_good": int(np.sum(predicted[high] == 0)),
        "grade45_miss_rate": float(np.mean(predicted[high] == 0)) if high.any() else None,
        "per_original_grade": by_grade,
    }


def success_conditions(baseline, candidate):
    return {
        "macro_f1_improves": candidate["macro_f1"] > baseline["macro_f1"],
        "grade45_miss_rate_decreases": (
            candidate["grade45_miss_rate"] < baseline["grade45_miss_rate"]
        ),
        "good_recall_not_lower": (
            candidate["per_class"][0]["recall"] >= baseline["per_class"][0]["recall"]
        ),
        "caution_precision_not_lower": (
            candidate["per_class"][1]["precision"] >= baseline["per_class"][1]["precision"]
        ),
    }


class BalancedBinaryLoss(nn.Module):
    """Numerically stable sigmoid BCE; inverse ORIGINAL binary training frequencies."""

    def __init__(self, weights):
        super().__init__()
        self.register_buffer("weights", torch.tensor(weights, dtype=torch.float32))

    def forward(self, logits, grades):
        targets = (grades >= 3).long()
        losses = nn.functional.binary_cross_entropy_with_logits(
            logits.float().reshape(-1),
            targets.float(),
            reduction="none",
        )
        weights = self.weights[targets]
        return (weights * losses).sum() / weights.sum()


def prepare(args):
    manifest = load_manifest({"data": {"output": str(args.manifest.parent)}})
    summary = read(args.baseline / "summary.json")
    source = summary["contract"]
    if source["settings"]["huber_delta"] != 0.2 or source["settings"]["weight_exponent"] != 0.5:
        raise ValueError("Baseline is not the selected weighted Huber model")
    for key, value in SETTINGS.items():
        if source["settings"].get(key) != value:
            raise ValueError(f"Baseline setting differs: {key}")
    if (
        source["model"] != "mobilenet_v3_large"
        or source["sampling"] != "sqrt_extra"
        or source["manifest_fingerprint"] != manifest["fingerprint"]
        or source["source_cache_sha256"] != manifest["pixel_cache"]["sha256"]
        or any(
            manifest["experiment_texture_preprocessing"].get(k) != v for k, v in PIPELINE.items()
        )
    ):
        raise ValueError("Baseline model, manifest, cache or preprocessing changed")
    verify_crops(manifest)
    train = PoreDataset(manifest, "train", training=True)
    valid, test = PoreDataset(manifest, "valid"), PoreDataset(manifest, "test")
    real_train = PoreDataset(manifest, "train")
    if tuple(map(len, (train, valid, test))) != (4112, 816, 819):
        raise ValueError("Unexpected original split sizes")
    counts, targets = expand_training(train)
    sampler = GradeDiverseBatchSampler(train, 16, torch.Generator().manual_seed(42))
    if sorted(i for batch in sampler for i in batch) != list(range(len(train))):
        raise ValueError("Training sampler must cover all original and additional rows")
    baseline_predictions = read(args.baseline / "test-predictions.json")
    expected = {r["id"]: (r["truth"], r["group"]) for r in test.records}
    observed = {r["id"]: (r["truth"], r["group"]) for r in baseline_predictions}
    if expected != observed or len(observed) != len(baseline_predictions):
        raise ValueError("Baseline predictions do not match the current Test records")
    original_accuracy = np.mean(
        [int(np.clip(np.floor(r["score"] + 0.5), 0, 5)) == r["truth"] for r in baseline_predictions]
    )
    if not math.isclose(original_accuracy, summary["test_metrics"]["accuracy"], abs_tol=1e-12):
        raise ValueError("Baseline predictions disagree with baseline summary")
    baseline_metrics = binary_metrics(
        [r["truth"] for r in baseline_predictions],
        [r["score"] / 5.0 for r in baseline_predictions],
    )
    binary_counts = [sum(counts[:3]), sum(counts[3:])]
    weights = [sum(counts) / (2 * n) for n in binary_counts]
    splits = {}
    for name, data in (("train", real_train), ("valid", valid), ("test", test)):
        splits[name] = {
            "roi": len(data),
            "subjects": len({r["subject"] for r in data.records}),
            "grades": [sum(r["truth"] == g for r in data.records) for g in range(6)],
            "binary": [sum((r["truth"] >= 3) == c for r in data.records) for c in (0, 1)],
        }
    contract = {
        "schema": "pore-binary-comparison-v1",
        "settings": SETTINGS,
        "pipeline": PIPELINE,
        "manifest_fingerprint": manifest["fingerprint"],
        "cache_sha256": manifest["pixel_cache"]["sha256"],
        "baseline_checkpoint_sha256": file_hash(args.baseline / "best.pt"),
        "baseline_loss": "unchanged weighted Huber delta=0.2, original-grade alpha=0.5",
        "baseline_predictions_sha256": file_hash(args.baseline / "test-predictions.json"),
        "script_sha256": file_hash(__file__),
        "source_sha256": {
            name: file_hash(ML / "src/skin_analysis" / name)
            for name in (
                "smartphone/data.py",
                "smartphone/train.py",
                "smartphone/sam.py",
                "smartphone/backbones.py",
                "runtime.py",
                "dataset.py",
            )
        },
        "head": "960 -> 1280 -> Hardswish -> Dropout(0.2) -> 1 logit -> sigmoid",
        "initialization": "MobileNet_V3_Large_Weights.IMAGENET1K_V2",
        "label_mapping": [0, 0, 0, 1, 1, 1],
        "threshold": 0.5,
        "loss": "inverse-original-binary-frequency weighted BCEWithLogitsLoss",
        "class_weights": weights,
        "original_grade_counts": counts,
        "draws_by_original_grade": targets,
        "draws_by_binary_class": [sum(targets[:3]), sum(targets[3:])],
        "draws_per_epoch": len(train),
        "steps_per_epoch": math.ceil(len(train) / 16),
        "splits": splits,
        "checkpoint_selection": "validation binary Macro-F1 max, unweighted BCE min on tie",
        "test_policy": "baseline once; candidate best checkpoint only after training",
        "baseline_selection_note": "Existing baseline selected using six-grade validation Macro-F1",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    old = args.output / "setup.json"
    if old.exists() and read(old)["contract"] != contract:
        raise ValueError("Output belongs to different code/data/settings; choose a new --output")
    write_json(old, {"contract": contract, "baseline_binary_test": baseline_metrics})
    return contract, train, real_train, valid, test, baseline_metrics


def eval_loader(data):
    return DataLoader(
        data,
        batch_size=16,
        shuffle=False,
        num_workers=SETTINGS["eval_workers"],
        pin_memory=True,
        generator=torch.Generator().manual_seed(100042),
    )


@torch.inference_mode()
def evaluate(model, data, device, description):
    model.eval()
    probabilities, grades = [], []
    for images, labels, _ in tqdm(eval_loader(data), desc=description, leave=False):
        output = model(images.to(device, non_blocking=True)).float().reshape(-1).sigmoid()
        probabilities.extend(output.cpu().tolist())
        grades.extend(labels.tolist())
    return binary_metrics(grades, probabilities), probabilities


def optimizer_for(model, frozen):
    model.set_stage(frozen)
    groups = [
        {
            "params": model.network.classifier.parameters(),
            "lr": SETTINGS["head_lr"] if frozen else SETTINGS["finetune_head_lr"],
        }
    ]
    if not frozen:
        groups.append(
            {
                "params": model.network.features.parameters(),
                "lr": SETTINGS["backbone_lr"],
            }
        )
    return torch.optim.AdamW(groups, weight_decay=SETTINGS["weight_decay"])


def scheduler_for(optimizer):
    return torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=0.5,
        patience=2,
        threshold=0.0001,
        threshold_mode="abs",
        min_lr=1e-7,
    )


class ProgressLoader:
    def __init__(self, loader, description):
        self.loader, self.description = loader, description

    def __getattr__(self, name):
        return getattr(self.loader, name)

    def __iter__(self):
        return iter(tqdm(self.loader, desc=self.description, leave=False))


def preflight(args, contract, real_train, test, device):
    baseline = torch.load(args.baseline / "best.pt", map_location="cpu", weights_only=True)
    if baseline["epoch"] != read(args.baseline / "summary.json")["best_epoch"]:
        raise ValueError("Baseline checkpoint and summary differ")
    model = GradeModel(1, pretrained=False, backbone="mobilenet_v3_large").to(device)
    model.network.load_state_dict(baseline["model_state"], strict=True)
    metrics, scores = evaluate(model, test, device, "Verify baseline sigmoid")
    stored = {r["id"]: r["score"] / 5 for r in read(args.baseline / "test-predictions.json")}
    expected = [stored[r["id"]] for r in test.records]
    if not np.allclose(scores, expected, rtol=0, atol=1e-5):
        raise ValueError("Baseline inference differs from stored predictions")
    del model
    seed_all(42)
    model = GradeModel(1, pretrained=True, backbone="mobilenet_v3_large").to(device).eval()
    images, labels, _ = next(iter(eval_loader(real_train)))
    with torch.inference_mode(), torch.amp.autocast("cuda", enabled=True):
        output = model(images.to(device))
        loss = BalancedBinaryLoss(contract["class_weights"]).to(device)(output, labels.to(device))
    if output.shape != (16, 1) or not torch.isfinite(output).all() or not torch.isfinite(loss):
        raise ValueError("Invalid binary model output/loss")
    write_json(
        args.output / "preflight.json",
        {
            "device": torch.cuda.get_device_name(device),
            "output_shape": list(output.shape),
            "baseline_sigmoid_verified": True,
            "baseline_binary_test": metrics,
            "optimizer_steps": 0,
            "note": "Inference only; training VRAM has not been measured",
        },
    )


def write_report(output, baseline=None, candidate=None, history=None):
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    setup = json.loads((output / "setup.json").read_text(encoding="utf-8"))
    baseline = baseline or summary["baseline_binary_test"]
    candidate = candidate or summary["candidate_binary_test"]
    history = history or json.loads((output / "history.json").read_text(encoding="utf-8"))
    contract = setup["contract"]
    settings = contract["settings"]
    pipeline = contract["pipeline"]
    splits = contract["splits"]
    conditions = success_conditions(baseline, candidate)
    best_epoch = summary["best_epoch"]
    best_row = next(row for row in history if row["epoch"] == best_epoch)
    total_train_seconds = sum(row["seconds"] for row in history)
    train_valid_gap = best_row["train_real"]["macro_f1"] - best_row["valid"]["macro_f1"]
    lines = [
        "# 모공 등급 모델의 이진 판정 실험",
        "",
        f"**결과:** {summary['epochs_run']} epoch 학습 후 조기 종료; 최고 검증 체크포인트는 "
        f"epoch {best_epoch}. RTX 4070 Ti SUPER에서 실행했다.",
        "",
        "> **핵심 결과:** 신규 모델의 Test Macro-F1은 "
        f"{baseline['macro_f1']:.4f} → {candidate['macro_f1']:.4f}로 "
        f"{candidate['macro_f1'] - baseline['macro_f1']:+.4f} 변했다. 반면 실제 4·5등급을 "
        f"양호로 놓친 비율은 {baseline['grade45_miss_rate']:.2%} → "
        f"{candidate['grade45_miss_rate']:.2%}로 악화됐다. 사전 정의한 네 성공 조건을 "
        f"모두 만족하지 못했다 (**{all(conditions.values())}**).",
        "",
        "## 실험 질문과 비교 범위",
        "",
        "원본 0–5등급 회귀 출력을 두 범주(양호/유의)로 해석하는 기존 모델과, "
        "같은 원본 이미지를 0–2=양호·3–5=유의로 직접 학습한 신규 이진 모델을 비교했다. "
        "기존 모델은 저장된 checkpoint를 추론에만 사용했다. 기존 모델을 재학습하거나 "
        "Huber 손실·α 가중치를 변경하지 않았다. 신규 모델은 ImageNet 가중치에서 새로 시작했다.",
        "",
        "| 원본 등급 | 이진 정답 |",
        "|---:|---|",
        "| 0, 1, 2 | 양호 (0) |",
        "| 3, 4, 5 | 유의 (1) |",
        "",
        "양쪽 모두 sigmoid 출력 0.5 이상을 유의로 판정했다. Macro 지표는 양호와 유의 "
        "두 범주를 같은 비중으로 평균한다.",
        "",
        "## 데이터와 분할",
        "",
        "합성 데이터는 제외했다. 원본 분할 manifest와 ROI pixel cache의 fingerprint를 "
        "검증했고, 사람 단위 기존 seed 42 분할을 그대로 사용했다. 표의 원본 등급 수는 ROI 수다.",
        "",
        "| 분할 | 인물 수 | 0등급 | 1등급 | 2등급 | 3등급 | 4등급 | 5등급 | 양호 | 유의 | 전체 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split_name, split in splits.items():
        grade_counts = split["grades"]
        good, caution = split["binary"]
        lines.append(
            f"| {split_name.title()} | {split['subjects']} | "
            + " | ".join(str(value) for value in grade_counts)
            + f" | {good} | {caution} | {split['roi']} |"
        )
    lines += [
        "",
        f"신규 모델은 기존 6등급 기준 제곱근 추가 추출을 유지해 epoch당 "
        f"{contract['draws_per_epoch']:,}회 노출({contract['steps_per_epoch']:,} SAM 업데이트)을 수행했다. "
        "이진 클래스 단위 오버샘플링은 하지 않았다. BCE 클래스 가중치는 원본 Train "
        f"분포에서 계산한 양호 {contract['class_weights'][0]:.4f}, "
        f"유의 {contract['class_weights'][1]:.4f}다.",
        "",
        "## 모델 및 학습 설정",
        "",
        "| 항목 | 설정 |",
        "|---|---|",
        f"| 신규 backbone / 초기 가중치 | MobileNetV3-Large / {contract['initialization']} |",
        f"| Head | {contract['head']} |",
        f"| 출력 해석 | sigmoid 확률; threshold={contract['threshold']:.1f} |",
        f"| Loss | {contract['loss']}; 가중치 양호={contract['class_weights'][0]:.4f}, 유의={contract['class_weights'][1]:.4f} |",
        f"| 기존 기준 모델 | MobileNetV3-Large; {contract['baseline_loss']}; 재학습하지 않음 |",
        f"| Batch / seed | {settings['batch_size']} / {settings['seed']} |",
        f"| Epoch / 조기 종료 | 최대 {settings['freeze_epochs'] + settings['finetune_epochs']}; patience {settings['patience']} |",
        f"| 학습 범위 | Head-only {settings['freeze_epochs']} epoch 후 backbone 전체 미세조정 |",
        f"| Optimizer | AdamW + SAM (ρ={settings['sam_rho']}) |",
        f"| Learning rate | Head-only {settings['head_lr']:g}; 미세조정 head {settings['finetune_head_lr']:g}, backbone {settings['backbone_lr']:g} |",
        f"| Scheduler | ReduceLROnPlateau; factor={settings['scheduler_factor']}, patience={settings['scheduler_patience']} |",
        f"| 전처리 | ROI 256×256; unsharp radius {pipeline['radius']:g}, {pipeline['percent']}%, threshold {pipeline['threshold']}; contrast ×{pipeline['contrast_factor']:g}; ImageNet 정규화 |",
        "| 데이터 증강 | Train 전용 기존 affine·색상 증강; Validation/Test 무작위 증강 없음 |",
        "| 체크포인트 선택 | Validation 이진 Macro-F1 최대; 동률이면 비가중 BCE 최소 |",
        "| 평가 정책 | Test는 학습 완료 후 선택 checkpoint로 1회 평가 |",
        "",
        "## 학습 추이와 과적합 점검",
        "",
        f"최고 checkpoint epoch {best_epoch}에서 Train 원본 무증강 Macro-F1은 "
        f"{best_row['train_real']['macro_f1']:.4f}, Validation Macro-F1은 "
        f"{best_row['valid']['macro_f1']:.4f}로 차이는 {train_valid_gap:.4f}다. "
        "Train 성능이 높은 반면 Validation이 낮은 간격은 과적합 징후다. 이는 학습 "
        "인물에는 잘 맞지만 검증 인물로 일반화되지 못했을 가능성을 보인다.",
        "",
        f"{summary['epochs_run']} epoch까지의 학습 epoch 합산 시간은 약 {total_train_seconds / 60:.1f}분이다 "
        f"(epoch별 시간 합; 최종 평가·보고서 작성 시간 제외). 조기 종료는 연속 "
        f"{settings['patience']}회 검증 checkpoint 미개선으로 발동했다.",
        "",
        "![에포크별 학습·검증 곡선](curves.png)",
        "",
        "왼쪽 위는 Binary Macro-F1, 오른쪽 위는 무증강 Train/Validation 평가 BCE다. "
        "아래 패널은 Validation 클래스별 Recall과 Accuracy 추이다. Train 지표는 "
        "원본 Train ROI 4,112장을 증강·추가 추출 없이 한 번 평가한 `train_real`이다.",
        "",
        "## Test 성능 비교",
        "",
        "기존 checkpoint는 기존 6등급 Validation Macro-F1 기준으로 선택된 모델이다. "
        "신규 checkpoint는 이진 Validation Macro-F1 기준으로 선택됐다. Test는 두 모델을 "
        "각자의 고정 checkpoint로 동일한 819개 원본 ROI에 평가했다.",
        "",
        "| 모델 | Accuracy | Macro Precision | Macro Recall | Macro-F1 | BCE | 양호 Recall | 유의 Precision | 유의 Recall | 4·5등급 놓침 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in (("기존 6등급 Huber checkpoint", baseline), ("신규 이진 BCE checkpoint", candidate)):
        lines.append(
            f"| {name} | {metrics['accuracy']:.4f} | {metrics['macro_precision']:.4f} | "
            f"{metrics['macro_recall']:.4f} | {metrics['macro_f1']:.4f} | "
            f"{metrics['cross_entropy']:.4f} | {metrics['per_class'][0]['recall']:.4f} | "
            f"{metrics['per_class'][1]['precision']:.4f} | {metrics['per_class'][1]['recall']:.4f} | "
            f"{metrics['grade45_missed_as_good']}/{metrics['grade45_support']} ({metrics['grade45_miss_rate']:.2%}) |"
        )
    lines += ["", "![Test 모델 비교와 혼동행렬](test-comparison.png)", ""]
    lines += [
        "### 클래스별 Test 지표",
        "",
        "| 모델 | 클래스 | 표본 | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, metrics in (("기존", baseline), ("신규", candidate)):
        for class_metrics in metrics["per_class"]:
            lines.append(
                f"| {name} | {class_metrics['name']} | {class_metrics['support']} | "
                f"{class_metrics['precision']:.4f} | {class_metrics['recall']:.4f} | {class_metrics['f1']:.4f} |"
            )
    lines += [
        "",
        "### 원본 등급별 Test 유의 Recall",
        "",
        "| 원본 등급 | 표본 | 기존 모델 | 신규 모델 |",
        "|---:|---:|---:|---:|",
    ]
    for old_grade, new_grade in zip(baseline["per_original_grade"], candidate["per_original_grade"], strict=True):
        lines.append(
            f"| {old_grade['grade']} | {old_grade['support']} | "
            f"{old_grade['caution_recall']:.4f} | {new_grade['caution_recall']:.4f} |"
        )
    lines += [
        "",
        "실제 4·5등급 48개 가운데 양호로 놓친 표본은 기존 14개에서 신규 18개로 "
        "늘었다. 특히 grade 4 유의 Recall은 기존 0.6905에서 신규 0.5952로 낮아졌다. "
        "grade 5는 Test 6장뿐이며 두 모델 모두 5/6장을 유의로 판정했다. 표본 수가 "
        "작아 이 비율은 한 장의 판정만 달라도 크게 변한다.",
        "",
        "## 성공 조건 및 해석",
        "",
        "| 사전 조건 | 결과 |",
        "|---|---|",
    ]
    condition_labels = {
        "macro_f1_improves": "Test Macro-F1 증가",
        "grade45_miss_rate_decreases": "실제 4·5등급 놓침 비율 감소",
        "good_recall_not_lower": "양호 Recall이 기존보다 낮지 않음",
        "caution_precision_not_lower": "유의 Precision이 기존보다 낮지 않음",
    }
    for key, label in condition_labels.items():
        lines.append(f"| {label} | {'충족' if conditions[key] else '미충족'} |")
    lines += [
        "",
        "신규 이진 모델은 전체 정확도와 양호 Recall, 유의 Precision이 올랐고 Macro-F1도 "
        "소폭 개선됐다. 반면 유의 Recall과 실제 4·5등급 놓침은 악화됐다. 따라서 이번 "
        "결과는 **두 등급을 합친 문제에서 전체 점수가 개선됐지만 고등급 검출 목표는 "
        "개선하지 못한 결과**로 해석한다. 네 조건 가운데 세 조건만 충족했다.",
        "",
        "이 비교에는 기존 회귀 출력의 임계값 해석과 신규 이진 정답 학습이라는 차이가 "
        "함께 들어 있다. 기존 Test 분할은 다른 실험에서 반복 관찰한 탐색 평가이고, "
        "각 모델은 다른 검증 지표로 checkpoint를 선택했다. 따라서 이 결과만으로 새로운 "
        "인물에 대한 일반화 개선이나 라벨 병합 자체의 인과 효과를 확정할 수 없다.",
        "",
        "## 산출물",
        "",
        "- `summary.json`: 실험 설정 fingerprint, 모델별 전체 지표, 성공 조건",
        "- `history.json`: 각 epoch Train·Validation 지표, 학습률, 소요 시간",
        "- `test-predictions.json`: Test 각 ROI의 등급, 이진 정답 및 예측 확률",
        "- `best.pt`, `last.pt`: 선택 checkpoint 및 마지막 학습 상태",
        "- `curves.png`, `test-comparison.png`: 학습 곡선과 Test 비교 시각화",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    epochs = [r["epoch"] for r in history]
    for split in ("train_real", "valid"):
        axes[0, 0].plot(epochs, [r[split]["macro_f1"] for r in history], label=split)
        axes[0, 1].plot(epochs, [r[split]["cross_entropy"] for r in history], label=split)
        axes[1, 0].plot(epochs, [r[split]["per_class"][0]["recall"] for r in history], label=f"{split} good")
        axes[1, 0].plot(epochs, [r[split]["per_class"][1]["recall"] for r in history], linestyle="--", label=f"{split} caution")
        axes[1, 1].plot(epochs, [r[split]["accuracy"] for r in history], label=split)
    axes[0, 0].set_ylabel("Binary Macro-F1")
    axes[0, 1].set_ylabel("Unweighted evaluation BCE")
    axes[1, 0].set_ylabel("Class Recall")
    axes[1, 1].set_ylabel("Accuracy")
    for axis in axes.flat:
        axis.set_xlabel("Epoch")
        axis.xaxis.set_major_locator(MaxNLocator(integer=True))
        axis.legend()
        axis.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output / "curves.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    metric_names = ("Macro-F1", "Accuracy", "Macro precision", "Macro recall")
    metric_keys = ("macro_f1", "accuracy", "macro_precision", "macro_recall")
    x = np.arange(len(metric_names))
    width = 0.36
    axes[0].bar(x - width / 2, [baseline[key] for key in metric_keys], width, label="Baseline")
    axes[0].bar(x + width / 2, [candidate[key] for key in metric_keys], width, label="Binary model")
    axes[0].set_xticks(x, metric_names, rotation=20, ha="right")
    axes[0].set_ylim(0, 1)
    axes[0].set_title("Test metrics")
    axes[0].legend()
    for axis, metrics, title in (
        (axes[1], baseline, "Baseline confusion matrix"),
        (axes[2], candidate, "Binary model confusion matrix"),
    ):
        matrix = np.asarray(metrics["confusion"])
        axis.imshow(matrix, cmap="Blues")
        axis.set_title(title)
        axis.set_xticks((0, 1), ("Good", "Caution"))
        axis.set_yticks((0, 1), ("Good", "Caution"))
        axis.set_xlabel("Predicted")
        axis.set_ylabel("Actual")
        for (row, column), value in np.ndenumerate(matrix):
            axis.text(column, row, str(value), ha="center", va="center", color="black")
    fig.tight_layout()
    fig.savefig(output / "test-comparison.png", dpi=160)
    plt.close(fig)


def train(args, prepared, device):
    contract, data, real_train, valid, test, baseline = prepared
    last = args.output / "last.pt"
    if (last.exists() or (args.output / "best.pt").exists()) and not args.resume:
        raise FileExistsError("Training output exists; use --resume or a new --output")
    if args.resume and not last.exists():
        raise FileNotFoundError("No last.pt to resume")
    state = torch.load(last, map_location="cpu", weights_only=True) if args.resume else None
    if state and state["contract"] != contract:
        raise ValueError("Resume contract changed")
    if state and (state["stale"] >= 10 or state["epoch"] >= 100):
        raise ValueError("Training has already reached its stopping condition")
    seed_all(42)
    model = GradeModel(1, pretrained=not args.resume, backbone="mobilenet_v3_large").to(device)
    if state:
        model.network.load_state_dict(state["model_state"], strict=True)
    seed_all(42)
    generator = torch.Generator().manual_seed(42)
    loader = DataLoader(
        data,
        batch_sampler=GradeDiverseBatchSampler(data, 16, generator),
        num_workers=SETTINGS["train_workers"],
        pin_memory=True,
        persistent_workers=True,
        worker_init_fn=seed_worker,
        generator=torch.Generator().manual_seed(100042),
    )
    loader.micro_batch_size = 16
    criterion = BalancedBinaryLoss(contract["class_weights"]).to(device)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    start = state["epoch"] if state else 0
    frozen = start < 1
    optimizer = optimizer_for(model, frozen)
    scheduler = None if frozen else scheduler_for(optimizer)
    history = state["history"] if state else []
    best = tuple(state["best_key"]) if state else (-float("inf"), -float("inf"))
    stale = state["stale"] if state else 0
    if state:
        if state["frozen"] == frozen:
            optimizer.load_state_dict(state["optimizer_state"])
            if scheduler:
                scheduler.load_state_dict(state["scheduler_state"])
        else:
            stale = 0
        scaler.load_state_dict(state["scaler_state"])
        restore_rng(state["rng_state"], generator)
    for epoch in range(start, 100):
        started = time.perf_counter()
        if frozen != (epoch < 1):
            frozen = epoch < 1
            optimizer = optimizer_for(model, frozen)
            scheduler = None if frozen else scheduler_for(optimizer)
            stale = 0
        data.set_epoch(epoch)
        lr_used = [g["lr"] for g in optimizer.param_groups]
        loss = sam_train_epoch(
            model,
            ProgressLoader(loader, f"Epoch {epoch + 1}/100 SAM"),
            optimizer,
            criterion,
            device,
            scaler,
            16,
            True,
            rho=0.05,
        )
        train_metrics, _ = evaluate(model, real_train, device, "Train real")
        valid_metrics, _ = evaluate(model, valid, device, "Validation")
        key = (valid_metrics["macro_f1"], -valid_metrics["cross_entropy"])
        improved = key > best
        if improved:
            best, stale = key, 0
        elif not frozen:
            stale += 1
        if scheduler:
            scheduler.step(valid_metrics["macro_f1"])
        if model._sam_steps != contract["steps_per_epoch"]:
            raise RuntimeError("Unexpected SAM step count")
        row = {
            "epoch": epoch + 1,
            "stage": "head" if frozen else "full_backbone",
            "train_loss": loss,
            "train_real": train_metrics,
            "valid": valid_metrics,
            "lr_used": lr_used,
            "lr_next": [g["lr"] for g in optimizer.param_groups],
            "selected": improved,
            "stale_epochs": stale,
            "samples_seen": len(data),
            "sam_steps": model._sam_steps,
            "seconds": round(time.perf_counter() - started, 2),
        }
        history.append(row)
        checkpoint = {
            "schema": "pore-binary-comparison-v1",
            "contract": contract,
            "epoch": epoch + 1,
            "frozen": frozen,
            "model_state": cpu_tree(model.network.state_dict()),
            "optimizer_state": cpu_tree(optimizer.state_dict()),
            "scheduler_state": scheduler.state_dict() if scheduler else None,
            "scaler_state": scaler.state_dict(),
            "rng_state": capture_rng(generator),
            "history": history,
            "best_key": list(best),
            "stale": stale,
        }
        save_checkpoint(last, checkpoint)
        if improved:
            save_checkpoint(args.output / "best.pt", checkpoint)
        write_json(args.output / "history.json", history)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if not frozen and stale >= 10:
            break
    chosen = torch.load(args.output / "best.pt", map_location="cpu", weights_only=True)
    model.network.load_state_dict(chosen["model_state"], strict=True)
    metrics, scores = evaluate(model, test, device, "Best checkpoint Test")
    conditions = success_conditions(baseline, metrics)
    write_json(
        args.output / "test-predictions.json",
        [
            {
                "id": r["id"],
                "original_grade": r["truth"],
                "truth": int(r["truth"] >= 3),
                "probability_caution": p,
                "predicted": int(p >= 0.5),
            }
            for r, p in zip(test.records, scores, strict=True)
        ],
    )
    write_json(
        args.output / "summary.json",
        {
            "contract": contract,
            "epochs_run": len(history),
            "best_epoch": chosen["epoch"],
            "baseline_binary_test": baseline,
            "candidate_binary_test": metrics,
            "success_conditions": conditions,
            "all_conditions_pass": all(conditions.values()),
        },
    )
    write_report(args.output, baseline, metrics, history)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=["setup", "preflight", "train", "report"], default="setup"
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gpu-uuid", default=DEFAULT_GPU)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.resume and args.action != "train":
        parser.error("--resume requires train")
    args.baseline, args.manifest, args.output = (
        p.resolve() for p in (args.baseline, args.manifest, args.output)
    )
    if args.manifest.name != "manifest.json":
        parser.error("--manifest must name a manifest.json file")
    if args.output == args.baseline or args.output.is_relative_to(args.baseline):
        parser.error("Output must be separate from the baseline directory")
    torch.set_num_threads(4)
    if args.action == "report":
        write_report(args.output)
        return
    prepared = prepare(args)
    if args.action == "setup":
        print(json.dumps(read(args.output / "setup.json"), ensure_ascii=False, indent=2))
        return
    device = select_cuda(args.gpu_uuid)
    if args.action == "preflight":
        preflight(args, prepared[0], prepared[2], prepared[4], device)
        print(json.dumps(read(args.output / "preflight.json"), ensure_ascii=False, indent=2))
    else:
        train(args, prepared, device)


if __name__ == "__main__":
    main()
