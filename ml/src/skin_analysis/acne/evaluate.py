"""One final paired evaluation, validation-only selection, and inference exports."""

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from ..dataset import make_loader
from ..runtime import cpu_tree, save_checkpoint, select_cuda
from ..train import predict_loader
from .common import file_hash, load_config, load_manifest, read_json, write_json
from .data import AcneDataset
from .metrics import binary_metrics, choose_threshold, paired_bootstrap
from .model import load_bundle


def stratified_metrics(records, scores, threshold):
    result = {}
    for field in ("age_range", "gender", "series"):
        result[field] = {}
        for value in sorted({r[field] for r in records}):
            indices = [i for i, r in enumerate(records) if r[field] == value]
            result[field][value] = binary_metrics(
                [records[i]["label"] for i in indices], scores[indices], threshold)
    return result


def latency(model, device):
    sample = torch.zeros(1, 3, 256, 256, device=device)
    times = []
    with torch.inference_mode():
        for _ in range(3):
            model(sample)
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        for _ in range(30):
            torch.cuda.synchronize(device)
            started = time.perf_counter()
            model(sample)
            torch.cuda.synchronize(device)
            times.append((time.perf_counter() - started) * 1000)
    return {"batch": 1, "precision": "float32", "input": [1, 3, 256, 256],
            "warmup": 3, "repeats": 30, "mean_ms": float(np.mean(times)),
            "p50_ms": float(np.median(times)), "p95_ms": float(np.quantile(times, .95)),
            "peak_process_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "scope": "model_only_dummy_input_excludes_decode_upload_and_other_NIA_models"}


def evaluate(config):
    manifest = load_manifest(config)
    settings = config["train"]
    root = Path(settings["output"])
    output = root / f"comparison-seed-{settings['seed']}"
    if (output / "report.json").exists():
        raise FileExistsError("Final test evaluation already exists; read its frozen report")
    # Check both completed runs before touching either test split.
    checkpoints = {}
    for source in ("imagenet", "nia"):
        run = root / f"{source}-seed-{settings['seed']}"
        done = read_json(run / "complete.json")
        if (done["epochs"] != settings["freeze_epochs"] + settings["finetune_epochs"]
                or done["manifest_fingerprint"] != manifest["fingerprint"]):
            raise ValueError("Both experiments must complete the same budget and manifest")
        checkpoints[source] = run / "best.pt"
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    datasets = {s: AcneDataset(manifest, s) for s in ("valid", "test", "official_audit")}
    results, predictions, selection_keys = {}, {}, {}
    trained_hash = None
    try:
        for source, path in checkpoints.items():
            started = time.perf_counter()
            model, bundle = load_bundle(path)
            if (bundle["manifest_fingerprint"] != manifest["fingerprint"]
                    or bundle["train_config"] != settings or bundle["source"] != source):
                raise ValueError("Checkpoint is not from the matched experiment")
            if trained_hash is not None and bundle["environment"] != trained_hash:
                raise ValueError("A/B training code or environment differs")
            trained_hash = bundle["environment"]
            model = model.to(device)
            torch.cuda.synchronize(device)
            load_ms = (time.perf_counter() - started) * 1000
            scores_by_split = {}
            for split, dataset in datasets.items():
                loader = make_loader(dataset, settings["batch_size"], settings["num_workers"],
                                     settings["seed"])
                _, scores, _ = predict_loader(model, loader, device, amp=False)
                scores_by_split[split] = scores.reshape(-1)
            valid_y = [r["label"] for r in datasets["valid"].records]
            threshold = choose_threshold(valid_y, scores_by_split["valid"])
            selection_keys[source] = tuple(bundle["best_key"])
            metrics = {}
            sample_rows = []
            for split, dataset in datasets.items():
                scores = scores_by_split[split]
                truth = [r["label"] for r in dataset.records]
                metrics[split] = {
                    "fixed_05": binary_metrics(truth, scores),
                    "validation_threshold": binary_metrics(truth, scores, threshold),
                    "groups": stratified_metrics(dataset.records, scores, threshold),
                }
                for row, score in zip(dataset.records, scores, strict=True):
                    predicted = int(score >= threshold)
                    sample_rows.append({
                        "id": row["id"], "split": split, "group_id": row["group_id"],
                        "label": row["label"], "score": float(score), "prediction": predicted,
                        "decision_threshold": threshold,
                        "error": "FN" if row["label"] == 1 and predicted == 0 else "FP"
                        if row["label"] == 0 and predicted == 1 else None,
                        "age_range": row["age_range"], "gender": row["gender"],
                        "series": row["series"], "lesion_count":
                        len(row["annotation"]["bbox"].get("lesions", [])),
                    })
            exported = {key: bundle[key] for key in (
                "architecture", "preprocessing", "class_mapping", "score_type", "initialization",
                "manifest_fingerprint", "environment", "validation_status", "limitations")}
            exported.update(model_state=cpu_tree(model.state_dict()), threshold=threshold,
                            selected_epoch=bundle["epoch"] + 1,
                            threshold_selection_split="internal_valid_only")
            inference_path = path.parent / "inference.pt"
            save_checkpoint(inference_path, exported)
            results[source] = {
                "best_epoch": bundle["epoch"] + 1, "validation_selection_key":
                list(selection_keys[source]), "threshold": threshold, "metrics": metrics,
                "latency": latency(model, device), "load_ms": load_ms,
                "checkpoint": str(inference_path), "sha256": file_hash(inference_path),
            }
            predictions[source] = scores_by_split
            write_json(output / f"{source}-predictions.json", sample_rows)
            del model, bundle
            torch.cuda.empty_cache()
        test = datasets["test"].records
        bootstrap = paired_bootstrap(
            [r["label"] for r in test], predictions["imagenet"]["test"],
            predictions["nia"]["test"], [r["group_id"] for r in test],
            config["evaluation"]["bootstrap_iterations"], settings["seed"])
        # Selection is deliberately independent of the test/audit scores above.
        winner = max(("imagenet", "nia"), key=lambda source: selection_keys[source])
        train_rows = [r for r in manifest["records"] if r["split"] == "train"]
        metadata_model = make_pipeline(DictVectorizer(), LogisticRegression(
            max_iter=1000, random_state=settings["seed"]))

        def features(rows):
            return [{k: str(r[k]) for k in ("age_range", "gender", "series")} for r in rows]

        metadata_model.fit(features(train_rows), [r["label"] for r in train_rows])
        metadata_metrics = {
            s: binary_metrics([r["label"] for r in d.records],
                              metadata_model.predict_proba(features(d.records))[:, 1])
            for s, d in datasets.items()}
        report = {
            "date_kst": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "evaluation_source_sha256": file_hash(__file__),
            "manifest_fingerprint": manifest["fingerprint"], "seed": settings["seed"],
            "experiments": results, "paired_test_bootstrap": bootstrap,
            "metadata_only_diagnostic": metadata_metrics,
            "metadata_only_features": ["generated_age_range", "generated_gender", "series"],
            "selected_for_local_research": winner,
            "selection_rule": "internal_valid_macro_f1_at_05_then_lower_bce_not_test",
            "deployment_ready": False, "limitations": manifest["limitations"],
        }
        write_json(output / "report.json", report)
        lines = ["# 여드름 이진 분류 비교 결과", "",
                 "합성 데이터 연구 결과입니다. 실사/임상 검증은 없습니다.", "",
                 "| 초기화 | 최적 epoch | Test Macro F1 (0.5) | ROC-AUC | 공식 Macro F1 (0.5) |",
                 "|---|---:|---:|---:|---:|"]
        for source, result in results.items():
            test_m = result["metrics"]["test"]["fixed_05"]
            audit_m = result["metrics"]["official_audit"]["fixed_05"]
            lines.append(f"| {source} | {result['best_epoch']} | {test_m['macro_f1']:.4f} | "
                         f"{test_m['roc_auc']:.4f} | {audit_m['macro_f1']:.4f} |")
        lines += ["", f"Validation 기준 선택: {winner}. 운영 배포 후보 확정이 아닙니다.",
                  f"NIA − ImageNet Test Macro F1 차이의 95% CI: {bootstrap['difference_ci95']}",
                  "", "## 한계", *[f"- {text}" for text in manifest["limitations"]]]
        (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print({"report": str(output / "report.json"), "selected": winner}, flush=True)
        return report
    finally:
        for dataset in datasets.values():
            dataset.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    evaluate(load_config(args.config) if args.config else load_config())


if __name__ == "__main__":
    main()
