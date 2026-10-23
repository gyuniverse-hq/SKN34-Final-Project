"""Fixed SAM candidates: train/valid/test audit, portable bundle and aggregate report."""

import json

import torch
from server.nia.recommendation import export_bundle

from skin_analysis.config import PROJECT_ROOT
from skin_analysis.runtime import select_cuda
from skin_analysis.smartphone.common import file_hash, load_config, load_manifest, write_json
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.focal_compare import verified_metrics
from skin_analysis.smartphone.train import GradeModel, make_loader, predict, verify_crops

ROOT = PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/final-model-report.md"


def main():
    config = load_config(PROJECT_ROOT / "configs/nia_smartphone_sam.toml")
    manifest = load_manifest(config)
    verify_crops(manifest)
    if (ROOT / "final-evaluation.json").exists():
        raise FileExistsError("Final evaluation already recorded")
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    results = {}
    for task, classes in (("pore", 6), ("pigmentation", 6), ("wrinkle", 7)):
        data = {s: GradeDataset(manifest, task, s) for s in ("train", "valid", "test")}
        loaders = {s: make_loader(d, config["train"]) for s, d in data.items()}
        variants = {}
        for name, base in (
            ("baseline_batch32", PROJECT_ROOT / "runs/nia-smartphone-seed-42"),
            ("sam_batch16", ROOT),
        ):
            path = base / task / "inference.bin"
            cp = torch.load(path, map_location="cpu", weights_only=True)
            summary = json.loads((path.parent / "summary.json").read_text("utf-8"))
            if (
                file_hash(path) != summary["sha256"]
                or cp["manifest_fingerprint"] != manifest["fingerprint"]
            ):
                raise ValueError("Checkpoint provenance mismatch")
            model = GradeModel(classes).to(device)
            model.network.load_state_dict(cp["model_state"], strict=True)
            splits = {}
            for split, loader in loaders.items():
                truth, predictions, probabilities, loss = predict(model, loader, device)
                metrics = verified_metrics(truth, predictions, classes)
                splits[split] = dict(**metrics, unweighted_ce=loss)
                write_json(
                    ROOT / "final-predictions" / f"{task}-{name}-{split}.json",
                    dict(
                        truth=truth,
                        predicted=predictions,
                        probabilities=probabilities,
                        subjects=[r["subject"] for r in data[split].records],
                    ),
                )
            variants[name] = dict(splits=splits, summary=summary)
            del model
        results[task] = variants
        del loaders
        print(json.dumps(dict(task=task, results=variants)), flush=True)
    result = dict(
        schema="nia-final-sam-evaluation-v1",
        tasks=results,
        data=manifest["summary"],
        fingerprint=manifest["fingerprint"],
        selection="WCE+AdamW+SAM fixed by user before test evaluation",
    )
    write_json(ROOT / "final-evaluation.json", result)
    write_json(REPORT.with_suffix(".metrics.json"), result)
    old_root = PROJECT_ROOT / "runs/nia-smartphone-seed-42/recommendation-bundle"
    bundle = json.loads((old_root / "manifest.json").read_text("utf-8"))
    for model in bundle["models"]:
        task = model["task"].split("/")[1]
        path = ROOT / task / "inference.bin"
        model.update(
            checkpoint=str(path),
            sha256=file_hash(path),
            source="Smartphone ResNet50 WCE+AdamW+SAM rho=.05 batch16 seed42",
        )
    bundle["acne"]["checkpoint"] = str(old_root / bundle["acne"]["checkpoint"])
    write_json(ROOT / "config.selected.json", bundle)
    export_bundle(ROOT / "config.selected.json", ROOT / "recommendation-bundle")
    lines = [
        "",
        "## 실제 전체 평가",
        "",
        "동일 인물 분할, 정답 ROI, 증강 없는 FP32 평가. 모든 값은 비율의 백분율이다.",
        "",
        "| 항목 | 모델 | 분할 | Accuracy | Macro P | Macro R | Macro F1 | MAE | ±1등급 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for task, variants in results.items():
        lines += [
            "",
            f"### {task}: 전체 지표",
            "",
            "| 항목 | 모델 | 분할 | Accuracy | Macro P | Macro R | Macro F1 | MAE | ±1등급 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, variant in variants.items():
            for split, m in variant["splits"].items():
                lines.append(
                    f"| {task} | {name} | {split} | {m['accuracy']:.2%} | "
                    f"{m['macro_precision']:.2%} | {m['macro_recall']:.2%} | "
                    f"{m['macro_f1']:.2%} | {m['mae']:.4f} | {m['within_one']:.2%} |"
                )
        baseline_valid = variants["baseline_batch32"]["splits"]["valid"]
        sam_valid = variants["sam_batch16"]["splits"]["valid"]
        da = (sam_valid["accuracy"] - baseline_valid["accuracy"]) * 100
        df = (sam_valid["macro_f1"] - baseline_valid["macro_f1"]) * 100
        lines += [
            "",
            f"### {task}: SAM 테스트 등급별 성능",
            "",
            f"검증 Accuracy 변화 {da:+.2f}%p, Macro-F1 변화 {df:+.2f}%p.",
            "",
            "| 등급 | 정답 수 | 예측 수 | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        m = variants["sam_batch16"]["splits"]["test"]
        for g in m["per_grade"]:
            lines.append(
                f"| {g['grade']} | {g['support']} | {g['predicted']} | "
                f"{g['precision']:.2%} | {g['recall']:.2%} | {g['f1']:.2%} |"
            )
        lines += [
            "",
            "혼동행렬(행=정답, 열=예측):",
            "",
            "```text",
            *[str(row) for row in m["confusion"]],
            "```",
            "",
            f"선택 가중치 SHA-256: `{variants['sam_batch16']['summary']['sha256']}`",
            "",
        ]
    prefix = REPORT.read_text("utf-8").split("\n## 실제 전체 평가")[0]
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
