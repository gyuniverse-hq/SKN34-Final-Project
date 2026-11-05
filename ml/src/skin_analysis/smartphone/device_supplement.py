"""Run and report rare-grade device-source supplementation experiments."""

import argparse
import collections
import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
import torch
from server.nia.imaging import crop_bounds
from server.nia.metrics import classification
from sklearn.metrics import (
    cohen_kappa_score,
    matthews_corrcoef,
    precision_recall_fscore_support,
)
from torch.utils.data import DataLoader

from ..runtime import select_cuda
from .common import PREPROCESSING, digest, file_hash, load_config, write_json
from .data import GradeDataset
from .train import GradeModel, make_loader, train_task, verify_crops

CONDITIONS = {
    "pad": {"smart_pad"},
    "camera": {"digital_camera"},
    "both": {"smart_pad", "digital_camera"},
}
DEVICE_DIRS = {
    "digital_camera": ("1. 디지털카메라", 0),
    "smart_pad": ("2. 스마트패드", 1),
}
SPLIT_DIRS = (("Training", "TS", "TL"), ("Validation", "VS", "VL"))


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _validate_base(path):
    base = json.loads(Path(path).read_text(encoding="utf-8"))
    claimed = base.pop("fingerprint")
    if digest(base) != claimed:
        raise ValueError("Base smartphone manifest fingerprint mismatch")
    base["fingerprint"] = claimed
    if base.get("schema") != "nia-smartphone-data-v1":
        raise ValueError("Expected the original audited smartphone manifest")
    if base.get("preprocessing") != PREPROCESSING:
        raise ValueError("Unexpected base preprocessing")
    records = [r for r in base["records"] if r["task"] == "pore"]
    groups = {}
    for record in records:
        prior = groups.setdefault(record["subject"], record["split"])
        if prior != record["split"]:
            raise ValueError(f"Base split leaks subject {record['subject']}")
    return base, records


def _source_roots(source_root, split, raw_code, label_code, device_folder):
    raw_kind = "원천데이터"
    label_kind = "라벨링데이터"
    data_root = Path(source_root) / "3.개방데이터" / "1.데이터"
    image_root = data_root / split / f"01.{raw_kind}" / raw_code / device_folder
    label_root = data_root / split / f"02.{label_kind}" / label_code / device_folder
    if not image_root.is_dir() or not label_root.is_dir():
        raise FileNotFoundError(f"Missing source directories for {split}/{device_folder}")
    return image_root, label_root


def _supplement_records(source_root, data_root, train_subject_groups, devices):
    records = []
    exclusions = collections.Counter()
    seen = set()
    for source_device in sorted(devices):
        folder, expected_device = DEVICE_DIRS[source_device]
        for split, raw_code, label_code in SPLIT_DIRS:
            image_root, label_root = _source_roots(source_root, split, raw_code, label_code, folder)
            for subject_dir in sorted(label_root.iterdir()):
                if not subject_dir.is_dir() or subject_dir.name not in train_subject_groups:
                    continue
                for label_path in sorted(subject_dir.glob("*.json")):
                    label = json.loads(label_path.read_text(encoding="utf-8"))
                    meta = label["images"]
                    if meta["device"] != expected_device:
                        raise ValueError(f"Device metadata mismatch: {label_path}")
                    part = meta["facepart"]
                    if part not in (5, 6):
                        continue
                    annotation_key = "l_cheek_pore" if part == 5 else "r_cheek_pore"
                    grade = label["annotations"].get(annotation_key)
                    if grade not in (4, 5):
                        continue
                    filename = label["info"]["filename"]
                    image_path = image_root / subject_dir.name / filename
                    if not image_path.is_file():
                        exclusions["missing_source_image"] += 1
                        continue
                    raw = image_path.read_bytes()
                    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        exclusions["decode_error"] += 1
                        continue
                    height, width = image.shape[:2]
                    if [width, height] != [meta["width"], meta["height"]]:
                        raise ValueError(f"Image dimensions disagree with JSON: {image_path}")
                    source_key = (source_device, filename, part)
                    if source_key in seen:
                        raise ValueError(f"Duplicate device ROI: {source_key}")
                    seen.add(source_key)
                    try:
                        x1, y1, x2, y2 = crop_bounds(meta["bbox"], width, height, part)
                    except (ValueError, TypeError):
                        exclusions["invalid_roi"] += 1
                        continue
                    crop = cv2.resize(
                        image[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LINEAR
                    )
                    ok, encoded = cv2.imencode(".jpg", crop)
                    if not ok:
                        raise ValueError(f"Could not encode crop: {image_path}")
                    photo_sha = sha256_bytes(raw)
                    pixel_sha = sha256_bytes(image.tobytes())
                    roi_id = digest([source_device, subject_dir.name, filename, part])
                    relative = f"device-crops/{source_device}/{roi_id}.jpg"
                    target_path = Path(data_root) / relative
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(encoded.tobytes())
                    records.append(
                        dict(
                            id=f"{roi_id}:pore",
                            subject=subject_dir.name,
                            group=train_subject_groups[subject_dir.name],
                            device=3,
                            source_device=source_device,
                            task="pore",
                            area="pore",
                            facepart=part,
                            truth=grade,
                            split="train",
                            path=relative,
                            crop_sha256=sha256_bytes(encoded.tobytes()),
                            image_sha256=photo_sha,
                            pixel_sha256=pixel_sha,
                            source_filename=filename,
                            source_label=label_path.name,
                            source_label_sha256=file_hash(label_path),
                        )
                    )
    return records, exclusions


def prepare_conditions(base_manifest_path, source_root, output_root):
    base, phone_records = _validate_base(base_manifest_path)
    data_root = Path(output_root) / "dataset"
    data_root.mkdir(parents=True, exist_ok=False)
    write_json(Path(output_root) / "baseline-manifest.json", base)
    source_crop_root = Path(base["root"])
    copied = set()
    for record in phone_records:
        relative = record["path"]
        if relative in copied:
            continue
        source = source_crop_root / relative
        target = data_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if file_hash(target) != record["crop_sha256"]:
            raise ValueError(f"Copied baseline crop hash mismatch: {relative}")
        copied.add(relative)
    train_subject_groups = {
        r["subject"]: r["group"] for r in phone_records if r["split"] == "train"
    }
    output = {}
    for condition, devices in CONDITIONS.items():
        additions, excluded = _supplement_records(
            source_root, data_root, train_subject_groups, devices
        )
        records = copy.deepcopy(phone_records) + additions
        for record in records:
            record.pop("cache_index", None)
        manifest = {
            **{k: v for k, v in base.items() if k not in {"fingerprint", "pixel_cache"}},
            "schema": "nia-smartphone-rare-grade-device-mix-v1",
            "root": str(data_root.resolve()),
            "records": records,
            "supplement": {
                "condition": condition,
                "source_devices": sorted(devices),
                "target_grades": [4, 5],
                "target_task": "pore",
                "training_subjects_only": True,
                "added_records": len(additions),
                "excluded": dict(excluded),
            },
        }
        manifest["summary"] = copy.deepcopy(base["summary"])
        manifest["summary"]["pore"]["train"] = {
            "n": sum(r["split"] == "train" for r in records),
            "subjects": len({r["subject"] for r in records if r["split"] == "train"}),
            "grade_support": [
                sum(r["split"] == "train" and r["truth"] == grade for r in records)
                for grade in range(6)
            ],
        }
        manifest["fingerprint"] = digest(manifest)
        condition_root = Path(output_root) / condition
        condition_root.mkdir(parents=True, exist_ok=False)
        write_json(condition_root / "manifest.json", manifest)
        supports = {
            split: [
                sum(r["truth"] == grade for r in records if r["split"] == split)
                for grade in range(6)
            ]
            for split in ("train", "valid", "test")
        }
        output[condition] = {
            "added_records": len(additions),
            "added_by_source": {
                device: sum(r["source_device"] == device for r in additions)
                for device in sorted(devices)
            },
            "added_by_grade": [sum(r["truth"] == grade for r in additions) for grade in range(6)],
            "supports": supports,
            "excluded": dict(excluded),
            "manifest": str(condition_root / "manifest.json"),
        }
    write_json(Path(output_root) / "prepared.json", output)
    return output


def run_conditions(config_path, experiment_root, source_root, base_manifest_path, selected=None):
    experiment_root = Path(experiment_root)
    prepared_path = experiment_root / "prepared.json"
    prepared = (
        json.loads(prepared_path.read_text(encoding="utf-8"))
        if prepared_path.is_file()
        else prepare_conditions(base_manifest_path, source_root, experiment_root)
    )
    config = load_config(config_path)
    device = select_cuda(config["train"].get("device_uuid"))
    torch.set_num_threads(4)
    for condition in selected or CONDITIONS:
        entry = prepared[condition]
        manifest = json.loads(Path(entry["manifest"]).read_text(encoding="utf-8"))
        claimed = manifest.pop("fingerprint")
        if digest(manifest) != claimed:
            raise ValueError(f"Manifest fingerprint mismatch: {condition}")
        manifest["fingerprint"] = claimed
        output = experiment_root / condition / "run"
        output.mkdir(parents=True, exist_ok=True)
        local_config = copy.deepcopy(config)
        local_config["train"]["output"] = str(output.resolve())
        verify_crops(manifest)
        print(
            json.dumps(
                {"event": "training_started", "condition": condition, "output": str(output)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        train_task(local_config, manifest, "pore", device)
        print(json.dumps({"event": "training_complete", "condition": condition}), flush=True)


def audit_loader(config_path, experiment_root, epochs=2):
    config = load_config(config_path)
    settings = config["train"]
    for condition in CONDITIONS:
        manifest_path = Path(experiment_root) / condition / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        claimed = manifest.pop("fingerprint")
        if digest(manifest) != claimed:
            raise ValueError(f"Manifest fingerprint mismatch: {condition}")
        manifest["fingerprint"] = claimed
        dataset = GradeDataset(
            manifest,
            "pore",
            "train",
            training=True,
            training_seed=settings["seed"],
        )
        loader = make_loader(
            dataset,
            settings,
            torch.Generator().manual_seed(settings["seed"]),
            training=True,
        )
        expected = set(range(len(dataset)))
        for epoch in range(epochs):
            dataset.set_epoch(epoch)
            seen = [int(index) for _, _, indices in loader for index in indices.tolist()]
            result = {
                "condition": condition,
                "epoch": epoch + 1,
                "expected_samples": len(dataset),
                "seen_samples": len(seen),
                "unique_samples": len(set(seen)),
                "missing_samples": len(expected - set(seen)),
                "duplicate_samples": len(seen) - len(set(seen)),
            }
            print(json.dumps(result), flush=True)
            if set(seen) != expected or len(seen) != len(expected):
                raise ValueError(f"Training loader did not use every ROI exactly once: {condition}")


def _extra_metrics(truth, predicted, classes):
    result = classification(truth, predicted, classes)
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, labels=list(range(classes)), average="micro", zero_division=0
    )
    result["micro_precision"] = float(precision)
    result["micro_recall"] = float(recall)
    result["micro_f1"] = float(f1)
    result["cohen_kappa"] = float(cohen_kappa_score(truth, predicted, labels=range(classes)))
    result["quadratic_weighted_kappa"] = float(
        cohen_kappa_score(truth, predicted, labels=range(classes), weights="quadratic")
    )
    result["matthews_corrcoef"] = float(matthews_corrcoef(truth, predicted))
    result["balanced_accuracy"] = result["macro_recall"]
    result["rmse"] = float(math.sqrt(np.mean((np.asarray(truth) - np.asarray(predicted)) ** 2)))
    return result


@torch.inference_mode()
def _predict(checkpoint_path, manifest, split, settings, device):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = GradeModel(6, pretrained=False, backbone="resnet50").to(device)
    model.network.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    dataset = GradeDataset(manifest, "pore", split, training=False)
    loader = DataLoader(
        dataset,
        batch_size=settings["batch_size"],
        shuffle=False,
        num_workers=settings["num_workers"],
        pin_memory=True,
    )
    truth, predicted, probabilities = [], [], []
    loss_total, n = 0.0, 0
    for images, labels, _ in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        logits = model(images)
        prob = torch.softmax(logits.float(), dim=1)
        loss_total += torch.nn.functional.cross_entropy(
            logits.float(), labels, reduction="sum"
        ).item()
        n += labels.numel()
        truth.extend(labels.cpu().tolist())
        predicted.extend(prob.argmax(1).cpu().tolist())
        probabilities.extend(prob.cpu().tolist())
    metrics = _extra_metrics(truth, predicted, 6)
    metrics["cross_entropy"] = loss_total / n
    one_hot = np.eye(6, dtype=np.float64)[truth]
    probs = np.asarray(probabilities, dtype=np.float64)
    metrics["multiclass_brier"] = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))
    metrics["truth"] = truth
    metrics["predicted"] = predicted
    metrics["probabilities"] = probabilities
    return metrics


def _metric_record(history, split_metrics, best_epoch):
    return {
        "training_epochs": len(history),
        "best_epoch": best_epoch,
        "epochs": history,
        "splits": split_metrics,
    }


def create_report(
    config_path, experiment_root, baseline_checkpoint, baseline_history, selected=None
):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    experiment_root = Path(experiment_root)
    config = load_config(config_path)
    device = select_cuda(config["train"].get("device_uuid"))
    settings = config["train"]
    report_root = experiment_root / "report"
    report_root.mkdir(parents=True, exist_ok=True)
    results = {}
    conditions = ("baseline", *(selected or CONDITIONS.keys()))
    for condition in conditions:
        if condition == "baseline":
            manifest_path = Path(experiment_root / "baseline-manifest.json")
            checkpoint_path = Path(baseline_checkpoint)
            history_path = Path(baseline_history)
        else:
            manifest_path = Path(experiment_root / condition / "manifest.json")
            checkpoint_path = experiment_root / condition / "run" / "pore" / "best.pt"
            history_path = experiment_root / condition / "run" / "pore" / "history.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "fingerprint" in manifest:
            claimed = manifest.pop("fingerprint")
            if digest(manifest) != claimed:
                raise ValueError(f"Manifest fingerprint mismatch: {condition}")
            manifest["fingerprint"] = claimed
        history = json.loads(Path(history_path).read_text(encoding="utf-8"))
        summary_path = checkpoint_path.parent / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        split_metrics = {
            split: _predict(checkpoint_path, manifest, split, settings, device)
            for split in ("valid", "test")
        }
        results[condition] = _metric_record(history, split_metrics, summary["best_epoch"])
        rows = history
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        epoch = [r["epoch"] for r in rows]
        axes[0].plot(epoch, [r.get("train_loss", np.nan) for r in rows], label="Train loss")
        axes[0].plot(epoch, [r.get("valid_loss", np.nan) for r in rows], label="Validation loss")
        axes[0].set(xlabel="Epoch", ylabel="Cross entropy", title=f"{condition}: loss")
        axes[0].legend()
        axes[1].plot(epoch, [r.get("valid_macro_f1", np.nan) for r in rows], marker="o")
        axes[1].set(
            xlabel="Epoch",
            ylabel="Macro-F1",
            ylim=(0, 1),
            title=f"{condition}: validation Macro-F1",
        )
        axes[1].grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(report_root / f"{condition}-learning-curves.png", dpi=160)
        plt.close(fig)
    write_json(report_root / "metrics.json", results)
    _plot_comparisons(results, report_root, conditions)
    _plot_validation_curves(results, report_root, conditions)
    _write_markdown(results, report_root, conditions)
    return results


def _plot_comparisons(results, report_root, conditions):
    import matplotlib.pyplot as plt

    metrics = ("macro_f1", "micro_f1", "weighted_f1", "balanced_accuracy")
    names = {
        "baseline": "Baseline phone",
        "pad": "Add smart pad",
        "camera": "Add digital camera",
        "both": "Add both",
    }
    labels = [names[c] for c in conditions]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    x = np.arange(len(conditions))
    width = 0.16
    for index, metric in enumerate(metrics):
        axes[0].bar(
            x + (index - (len(metrics) - 1) / 2) * width,
            [results[c]["splits"]["test"][metric] for c in conditions],
            width,
            label=metric.replace("_", " "),
        )
    axes[0].set_xticks(x, labels, rotation=20, ha="right")
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("Score")
    axes[0].set_title("Held-out smartphone test metrics")
    axes[0].legend(fontsize=8, ncols=2)
    recalls = [results[c]["splits"]["test"]["per_grade"] for c in conditions]
    for i, _ in enumerate(conditions):
        axes[1].plot(range(6), [g["recall"] for g in recalls[i]], marker="o", label=labels[i])
    axes[1].set_xticks(range(6))
    axes[1].set_ylim(0, 1)
    axes[1].set_xlabel("Pore grade")
    axes[1].set_ylabel("Recall")
    axes[1].set_title("Per-grade test Recall")
    axes[1].grid(alpha=0.25)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(report_root / "test-metric-comparison.png", dpi=160)
    plt.close(fig)


def _plot_validation_curves(results, report_root, conditions):
    import matplotlib.pyplot as plt

    names = {
        "baseline": "Baseline phone",
        "pad": "Add smart pad",
        "camera": "Add digital camera",
        "both": "Add both",
    }
    labels = [names[c] for c in conditions]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for condition, label in zip(conditions, labels, strict=True):
        rows = results[condition]["epochs"]
        epochs = [row["epoch"] for row in rows]
        axes[0].plot(epochs, [row.get("valid_macro_f1", np.nan) for row in rows], label=label)
        axes[1].plot(epochs, [row.get("valid_loss", np.nan) for row in rows], label=label)
    axes[0].set(xlabel="Epoch", ylabel="Macro-F1", ylim=(0, 1), title="Validation Macro-F1")
    axes[1].set(xlabel="Epoch", ylabel="Cross entropy", title="Validation loss")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(report_root / "validation-curves.png", dpi=160)
    plt.close(fig)


def _write_markdown(results, report_root, conditions):
    prepared = json.loads((report_root.parent / "prepared.json").read_text(encoding="utf-8"))
    rows = []
    data_rows = []
    grade_rows = []
    labels = {
        "baseline": "스마트폰 기준 모델",
        "pad": "스마트패드 보충",
        "camera": "디지털 카메라 보충",
        "both": "두 장비 보충",
    }
    for condition in conditions:
        test = results[condition]["splits"]["test"]
        valid = results[condition]["splits"]["valid"]
        rows.append(
            f"| {labels[condition]} | {results[condition]['best_epoch']} | "
            f"{valid['macro_f1']:.3f} | {test['accuracy']:.3f} | "
            f"{test['macro_precision']:.3f} | {test['macro_recall']:.3f} | "
            f"{test['macro_f1']:.3f} | {test['micro_precision']:.3f} | "
            f"{test['micro_recall']:.3f} | {test['micro_f1']:.3f} | "
            f"{test['weighted_precision']:.3f} | {test['weighted_recall']:.3f} | "
            f"{test['weighted_f1']:.3f} | {test['mae']:.3f} | {test['within_one']:.3f} | "
            f"{test['cohen_kappa']:.3f} | {test['quadratic_weighted_kappa']:.3f} | "
            f"{test['matthews_corrcoef']:.3f} | {test['cross_entropy']:.3f} | "
            f"{test['multiclass_brier']:.3f} |"
        )
        if condition != "baseline":
            source = prepared[condition]
            data_rows.append(
                f"| {labels[condition]} | {source['added_records']} | "
                f"{source['added_by_grade'][4]} | {source['added_by_grade'][5]} | "
                f"{sum(source['supports']['train'])} | "
                f"{source['supports']['train'][4]} | {source['supports']['train'][5]} |"
            )
    for grade in range(6):
        support = results["baseline"]["splits"]["test"]["per_grade"][grade]["support"]
        recalls = [
            results[condition]["splits"]["test"]["per_grade"][grade]["recall"]
            for condition in conditions
        ]
        grade_rows.append(
            f"| {grade} | {support} | " + " | ".join(f"{value:.3f}" for value in recalls) + " |"
        )
    pooled45 = {}
    three_to_two = {}
    for condition in conditions:
        test = results[condition]["splits"]["test"]
        support45 = test["per_grade"][4]["support"] + test["per_grade"][5]["support"]
        pooled45[condition] = (
            test["per_grade"][4]["recall"] * test["per_grade"][4]["support"]
            + test["per_grade"][5]["recall"] * test["per_grade"][5]["support"]
        ) / support45
        three_to_two[condition] = test["confusion"][3][2]
    lines = [
        "# 모공 희소등급 타 장비 사진 보충 실험",
        "",
        "학습 분할의 4·5등급 모공 ROI에 해당하는 타 기기 사진을 추가했다. "
        "검증·테스트 인물은 보충 데이터에서 제외했으며 평가에는 스마트폰 사진만 사용했다.",
        "",
        "## 테스트 결과",
        "",
        "검증 Macro-F1으로 체크포인트를 선택했다. 테스트 폴드는 이전 실험에서도 확인했으므로 "
        "완전히 새로운 최종 평가셋으로 해석하지 않는다.",
        "",
        "## 학습 데이터 보충량",
        "",
        "| 조건 | 추가 ROI | 추가 4등급 | 추가 5등급 | 전체 학습 ROI | 학습 4등급 | 학습 5등급 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *data_rows,
        "",
        "| 조건 | Best epoch | Valid Macro-F1 | Accuracy | Macro-P | Macro-R | Macro-F1 | "
        "Micro-P | Micro-R | Micro-F1 | Weighted-P | Weighted-R | Weighted-F1 | MAE | "
        "±1등급 | Cohen κ | Quadratic κ | MCC | CE loss | Brier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "## 등급별 Recall",
        "",
        "| 실제 등급 | 테스트 표본 | " + " | ".join(labels[c] for c in conditions) + " |",
        "|---:|---:|" + "---:|" * len(conditions),
        *grade_rows,
        "",
        "| 조건 | 4·5등급 통합 Recall | 실제 3등급을 2등급으로 예측 |",
        "|---|---:|---:|",
        *[f"| {labels[c]} | {pooled45[c]:.3f} | {three_to_two[c]} |" for c in conditions],
        "",
        "다중 클래스 단일 라벨 분류에서 Micro-F1은 Accuracy와 같습니다. "
        "Balanced Accuracy는 Macro Recall과 같습니다.",
        "",
        "## 그래프",
        "",
        "![테스트 지표 및 등급별 Recall](test-metric-comparison.png)",
        "",
        "![검증 지표의 에포크별 변화](validation-curves.png)",
        "",
        "각 조건의 학습·검증 곡선은 조건 이름의 `-learning-curves.png` 파일에 있다. "
        "`metrics.json`에는 검증·테스트의 추가 지표, 등급별 점수와 혼동행렬이 기록되어 있다.",
        "",
        "## 해석 주의점",
        "",
        "조건 비교는 검증 성능을 우선해 해석한다. "
        "희소 등급의 표본과 인물이 적어 등급별 지표가 불안정할 수 있다.",
        "",
        "보충 사진은 같은 인물의 다른 장비 촬영이므로 희소 등급의 인물 수 자체를 늘리지는 않는다. "
        "4·5등급에만 장비가 추가되는 설정은 장비와 등급의 연관을 학습할 위험이 있다. "
        "테스트 결과는 이번 고정 비교 조건의 평가로만 해석하고, "
        "다른 촬영 환경에 대한 일반화로 확대하지 않는다.",
        "",
    ]
    (report_root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--baseline-checkpoint", type=Path)
    parser.add_argument("--baseline-history", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--condition", choices=list(CONDITIONS), action="append")
    parser.add_argument("--audit-loader", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.prepare_only:
        result = prepare_conditions(args.base_manifest, args.source_root, args.experiment_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.train:
        run_conditions(
            args.config, args.experiment_root, args.source_root, args.base_manifest, args.condition
        )
    if args.audit_loader:
        audit_loader(args.config, args.experiment_root)
    if args.report:
        if not args.baseline_checkpoint or not args.baseline_history:
            parser.error("--report requires --baseline-checkpoint and --baseline-history")
        create_report(
            args.config,
            args.experiment_root,
            args.baseline_checkpoint,
            args.baseline_history,
            args.condition,
        )


if __name__ == "__main__":
    main()
