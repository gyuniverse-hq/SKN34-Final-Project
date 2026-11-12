"""Retrain the retained seven-feature CatBoost on the frozen final splits only."""

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path

import joblib
import numpy as np
from catboost import CatBoostClassifier
from tqdm import tqdm

from scripts.data.recommendation.training_common import PARTS, evaluate, write_json

ROOT = Path(__file__).resolve().parents[3]
FINAL = ROOT / "ml/experiments/recommendation-v2-image-feature-replacement-20261111"
SCHEMA = (
    ROOT
    / "ml/data/recommendation-v2/catboost-skin-condition-20261111/encoding_metadata.json"
)
FEATURES = [
    "age_group",
    "gender",
    "skin_type",
    "primary_concern",
    "pore",
    "wrinkle",
    "tone",
]


def load_final_data(source, schema_path):
    protocol = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if (
        protocol["image_model_features"] != FEATURES
        or not protocol["replace_condition"]
    ):
        raise ValueError("Expected the final seven-feature contract")
    if protocol["label_count"] != len(schema["labels"]):
        raise ValueError("Label schema mismatch")
    data, hashes = {}, {}
    for part in PARTS:
        raw = (source / f"{part}.jsonl").read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        if len(rows) != protocol["counts"][part] or not rows:
            raise ValueError("Frozen split count mismatch")
        sources = [row["source"] for row in rows]
        if len(set(sources)) != len(sources):
            raise ValueError("Duplicate source")
        for row in rows:
            if len(row["image_features"]) != 3 or any(
                v not in ("양호", "주의") for v in row["image_features"]
            ):
                raise ValueError("Invalid analysis categories")
            if any(
                row["base_x"][key] not in schema["categories"][key]
                for key in FEATURES[:4]
            ):
                raise ValueError("Invalid demographic or concern category")
            if any(
                not row[field]
                for field in ("group_id", "original_group_id", "image_group_id")
            ):
                raise ValueError("Missing group identity")
        x = np.asarray(
            [
                [row["base_x"][k] for k in FEATURES[:4]] + row["image_features"]
                for row in rows
            ],
            dtype=object,
        )
        y = np.asarray([row["y"] for row in rows])
        if (
            y.shape != (len(rows), len(schema["labels"]))
            or not np.isin(y, [0, 1]).all()
        ):
            raise ValueError("Invalid multi-hot targets")
        data[part] = (rows, x, y.astype(np.uint8))
        hashes[part] = hashlib.sha256(raw).hexdigest()
    for left, right in combinations(PARTS, 2):
        for field in ("source", "group_id", "original_group_id", "image_group_id"):
            if {r[field] for r in data[left][0]} & {r[field] for r in data[right][0]}:
                raise ValueError(f"Cross-split leakage: {field}")
    return protocol, schema, data, hashes


def ranking_metrics(y, scores, labels, k=5):
    ids = [label["db_id"] for label in labels]
    order = np.asarray(
        [sorted(range(len(ids)), key=lambda i: (-row[i], ids[i]))[:k] for row in scores]
    )
    hits = np.take_along_axis(y, order, axis=1).sum(axis=1)
    return {
        f"precision_at_{k}": float(np.mean(hits / k)),
        f"recall_at_{k}": float(np.mean(hits / np.maximum(y.sum(axis=1), 1))),
    }


class Progress:
    def __init__(self, bar):
        self.bar = bar

    def after_iteration(self, info):
        self.bar.update(info.iteration - self.bar.n)
        return True


def train(source, schema_path, output):
    if output.exists():
        raise ValueError("Choose a new output directory")
    protocol, schema, data, hashes = load_final_data(source, schema_path)
    config = protocol["config"]
    if config["model"] != "catboost":
        raise ValueError("Expected CatBoost")
    model = CatBoostClassifier(
        loss_function="MultiLogloss",
        iterations=config["iterations"],
        depth=config["depth"],
        learning_rate=config["learning_rate"],
        l2_leaf_reg=3,
        one_hot_max_size=config["one_hot_max_size"],
        random_seed=config["seed"],
        thread_count=config["threads"],
        task_type="CPU",
        allow_writing_files=False,
        allow_const_label=True,
        verbose=False,
    )
    # Validation/test never enter fit, early stopping, or hyperparameter selection.
    with tqdm(total=config["iterations"], desc="V2 CatBoost", unit="iteration") as bar:
        model.fit(
            data["training"][1],
            data["training"][2],
            cat_features=list(range(len(FEATURES))),
            callbacks=[Progress(bar)],
        )
    output.mkdir(parents=True)
    folder = output / "image"
    folder.mkdir()
    joblib.dump(model, folder / "model.joblib", compress=3)
    restored = joblib.load(folder / "model.joblib")
    metrics = {}
    for part in ("validation", "test"):
        rows, x, y = data[part]
        scores = model.predict_proba(x)
        np.testing.assert_allclose(
            restored.predict_proba(x), scores, atol=1e-12, rtol=0
        )
        values, per_label, _, pred = evaluate(
            y, scores, config["threshold"], schema["labels"]
        )
        values.update(ranking_metrics(y, scores, schema["labels"]))
        metrics[part] = values
        write_json(folder / f"{part}_per_label.json", per_label)
        np.savez_compressed(
            folder / f"{part}_predictions.npz",
            y_true=y,
            probabilities=scores,
            y_pred=pred,
            sources=np.asarray([r["source"] for r in rows]),
        )
    write_json(folder / "result.json", {"params": config, "metrics": metrics})
    write_json(output / "protocol.json", protocol)
    write_json(
        output / "retraining_audit.json",
        {
            "input_sha256": hashes,
            "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            "features": FEATURES,
            "counts": {part: len(data[part][0]) for part in PARTS},
            "training_only_fit": True,
            "hyperparameters_and_threshold": "frozen; no selection on validation/test",
        },
    )
    # Preserve the exact input splits so the native-bundle exporter can verify predictions.
    for part in PARTS:
        (output / f"{part}.jsonl").write_bytes((source / f"{part}.jsonl").read_bytes())
    lines = [
        "# V2 최종 데이터 재학습",
        "",
        "기존 분할·설정 고정. 검증/테스트는 평가에만 사용.",
        "",
        "| 구간 | P@5 | Recall@5 | Precision micro | macro-F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for part, m in metrics.items():
        lines.append(
            f"| {part} | {m['precision_at_5']:.4f} | {m['recall_at_5']:.4f} | "
            f"{m['precision_micro']:.4f} | {m['f1_macro']:.4f} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=FINAL)
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        _, _, data, hashes = load_final_data(args.source, args.schema)
        print(
            json.dumps(
                {"counts": {p: len(data[p][0]) for p in PARTS}, "sha256": hashes}
            )
        )
    elif args.output is None:
        parser.error("--output is required unless --check-only is used")
    else:
        print(
            json.dumps(train(args.source, args.schema, args.output), ensure_ascii=False)
        )


if __name__ == "__main__":
    main()
