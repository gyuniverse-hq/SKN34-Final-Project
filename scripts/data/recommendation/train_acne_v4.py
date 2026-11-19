"""Train an eleven-feature model and compare it with the frozen V3 bundle."""

import argparse
import hashlib
import json
import math
from itertools import combinations
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "ml/data/recommendation-v2/reviewed-acne-v41-20261117"
ORIGINAL = ROOT / "ml/data/recommendation-v2/reviewed-20261114"
EXPERIMENT = ROOT / "ml/experiments/recommendation-v2-score-weight-ablation-20261114"
V3 = ROOT / "ml/runs/recommend-cat-v3/bundle"
FEATURES = ["age_group", "gender", "skin_type", "primary_concern", "pore", "wrinkle", "tone"]
SCORES = ["pore_score", "wrinkle_score", "pigmentation_score", "acne_score"]
PARTS = ("training", "validation", "test")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(y, probabilities, labels):
    ids = np.array([label["db_id"] for label in labels])
    order = np.lexsort((np.broadcast_to(ids, probabilities.shape), -probabilities), axis=1)
    ranked = np.take_along_axis(y, order, axis=1)
    hits = ranked[:, :5].sum(axis=1)
    counts = y.sum(axis=1)
    predicted = np.zeros_like(y)
    np.put_along_axis(predicted, order[:, :5], 1, axis=1)
    supported = counts > 0
    if not supported.all():
        raise ValueError("R-precision requires nonempty targets")
    return {
        "precision_at_5": float(np.mean(hits / 5)),
        "recall_at_5": float(np.mean(hits / counts)),
        "r_precision": float(np.mean([row[:int(n)].sum() / n for row, n in zip(ranked, counts, strict=True)])),
        "top_5_f1_micro": float(f1_score(y, predicted, average="micro", zero_division=0)),
        "top_5_f1_macro": float(f1_score(y, predicted, average="macro", zero_division=0)),
        "top_5_f1_macro_supported": float(f1_score(y[:, y.sum(axis=0) > 0], predicted[:, y.sum(axis=0) > 0], average="macro", zero_division=0)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.bundle.exists():
        raise FileExistsError("Choose new experiment and bundle directories")
    source_manifest = json.loads((SOURCE / "protocol.json").read_text(encoding="utf-8"))
    v3_manifest = json.loads((V3 / "manifest.json").read_text(encoding="utf-8"))
    prior = json.loads((EXPERIMENT / "protocol.json").read_text(encoding="utf-8"))
    if v3_manifest["features"] != FEATURES + SCORES[:3] or sha256(V3 / "model.cbm") != v3_manifest["modelSha256"]:
        raise ValueError("V3 bundle contract or hash mismatch")
    if source_manifest["source_split_sha256"] != prior["input_sha256"]:
        raise ValueError("Source splits differ from V3 experiment")
    labels = v3_manifest["labels"]
    if len(labels) != 80 or sha256(SOURCE / "encoding_metadata.json") != v3_manifest["schemaSha256"]:
        raise ValueError("Label schema mismatch")
    data = {}
    for part in PARTS:
        path = SOURCE / f"{part}.jsonl"
        original_path = ORIGINAL / f"{part}.jsonl"
        if sha256(path) != source_manifest["output_split_sha256"][part] or sha256(original_path) != prior["input_sha256"][part]:
            raise ValueError(f"Split hash mismatch: {part}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        original = [json.loads(line) for line in original_path.read_text(encoding="utf-8").splitlines()]
        if len(rows) != prior["counts"][part] or len(rows) != len(original):
            raise ValueError("Split count mismatch")
        values, targets = [], []
        for row, previous in zip(rows, original, strict=True):
            scores = row.pop("image_scores")
            if row != previous or set(scores) != set(SCORES):
                raise ValueError("Source row or score fields changed")
            numeric = [scores[name] for name in SCORES]
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in numeric):
                raise ValueError("Invalid numeric score")
            if len(row["y"]) != 80 or not set(row["y"]) <= {0, 1}:
                raise ValueError("Invalid target")
            values.append([row["base_x"][name] for name in FEATURES[:4]] + row["image_features"] + numeric)
            targets.append(row["y"])
        data[part] = (original, np.asarray(values, dtype=object), np.asarray(targets, dtype=np.uint8))
    for left, right in combinations(PARTS, 2):
        for field in ("source", "group_id", "original_group_id", "image_group_id"):
            if {r[field] for r in data[left][0]} & {r[field] for r in data[right][0]}:
                raise ValueError(f"Cross-split overlap: {field}")

    baseline = CatBoostClassifier()
    baseline.load_model(str(V3 / "model.cbm"))
    old_metrics = json.loads((EXPERIMENT / "scores/metrics.json").read_text(encoding="utf-8"))
    comparisons = {}
    for part in ("validation", "test"):
        rows, x, y = data[part]
        prediction = baseline.predict_proba(x[:, :10])
        with np.load(EXPERIMENT / f"scores/{part}_predictions.npz") as saved:
            np.testing.assert_array_equal(saved["sources"], [r["source"] for r in rows])
            np.testing.assert_array_equal(saved["y_true"], y)
            np.testing.assert_allclose(prediction, saved["probabilities"], atol=1e-12, rtol=0)
        calculated = metrics(y, prediction, labels)
        for name, value in calculated.items():
            if not math.isclose(value, old_metrics[part][name], abs_tol=1e-12):
                raise ValueError(f"V3 metric mismatch: {part}/{name}")
        comparisons[part] = {"v3": calculated}
    print("V3 baseline and saved predictions verified; training V4", flush=True)
    params = dict(prior["params"])
    model = CatBoostClassifier(**params)
    model.fit(data["training"][1], data["training"][2], cat_features=list(range(7)))
    for part in ("validation", "test"):
        _, x, y = data[part]
        comparisons[part]["v4"] = metrics(y, model.predict_proba(x), labels)

    args.bundle.mkdir(parents=True, exist_ok=False)
    model_path = args.bundle / "model.cbm"
    model.save_model(str(model_path))
    restored = CatBoostClassifier()
    restored.load_model(str(model_path))
    for part in ("validation", "test"):
        np.testing.assert_allclose(restored.predict_proba(data[part][1]), model.predict_proba(data[part][1]), atol=1e-12, rtol=0)
    manifest = {**v3_manifest, "version": "recommend-cat-v4", "features": FEATURES + SCORES,
                "numericFeatures": SCORES, "numericRanges": {**v3_manifest["numericRanges"], "acne_score": [0.0, 1.0]},
                "modelSha256": sha256(model_path), "verifiedTestRows": len(data["test"][0]),
                "sourceExperiment": str(args.output), "sourceVariant": "acne-score",
                "trainingContract": {**v3_manifest["trainingContract"], "acneModelSha256": source_manifest["acne_model_sha256"],
                                     "acneScoreKind": "uncalibrated_ldl_aggregated_score",
                                     "acneInput": "entire source image, Pillow bilinear 256 then 224",
                                     "acneMobileEquivalenceValidated": False},
                "deploymentStatus": "serving_unvalidated"}
    manifest.pop("sourceSha256", None)
    (args.bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"counts": prior["counts"], "params": params, "features_v3": FEATURES + SCORES[:3],
              "features_v4": FEATURES + SCORES, "source_hashes": source_manifest["output_split_sha256"],
              "v3_sha256": v3_manifest["modelSha256"], "v4_sha256": manifest["modelSha256"],
              "training_only": True, "baseline_predictions_verified": True, "metrics": comparisons}
    (args.output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 추천 모델 V3·V4 비교", "", "동일 분할·Y·고정 학습 설정. V4 X에 트러블 점수 하나 추가.", "",
             "| 구간 | 모델 | R-Precision | P@5 | Recall@5 | Top-5 micro-F1 | Top-5 macro-F1 (80종) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for part in ("validation", "test"):
        for version in ("v3", "v4"):
            m = comparisons[part][version]
            lines.append(f"| {part} | {version} | {m['r_precision']:.4%} | {m['precision_at_5']:.4%} | {m['recall_at_5']:.4%} | {m['top_5_f1_micro']:.4%} | {m['top_5_f1_macro']:.4%} |")
    lines += ["", "기존 테스트셋을 이미 관찰한 단일 seed 비교이며 독립적인 최종 성능 평가가 아니다.",
              "성분 정답과의 일치도이며 실제 제품 효능이나 사용자 만족도를 뜻하지 않는다.",
              "트러블 모델은 정상 피부가 학습·평가에 포함되지 않았고 기존 이미지와 앱 입력의 동등성은 미검증이다.",
              "V4는 개발용 추천 비교 API에서 선택하며 피부 분석 v4.1 트러블 점수가 필요하다."]
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
