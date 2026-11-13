"""Export trusted local CatBoost; assert all saved test predictions agree."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = (
    ROOT / "ml/experiments/recommendation-v2-image-feature-replacement-20261111"
)
SCHEMA = (
    ROOT
    / "ml/data/recommendation-v2/catboost-skin-condition-20261111/encoding_metadata.json"
)


def bundle_destination(model_name, output=None):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", model_name):
        raise ValueError("Model name must use lowercase letters, digits and hyphens")
    return Path(output) if output is not None else ROOT / "ml/runs" / model_name / "bundle"


def export(output=None, experiment=EXPERIMENT, schema_path=SCHEMA, model_name="recommend-cat-v2"):
    import joblib
    import numpy as np
    from catboost import CatBoostClassifier

    output = bundle_destination(model_name, output)
    if output.exists():
        raise ValueError("Choose a new bundle directory")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    protocol = json.loads((experiment / "protocol.json").read_text(encoding="utf-8"))
    source = experiment / "image/model.joblib"
    model = joblib.load(source)
    rows = [
        json.loads(s)
        for s in (experiment / "test.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    features = protocol["image_model_features"]
    x = [[r["base_x"][k] for k in features[:4]] + r["image_features"] for r in rows]
    expected = np.load(experiment / "image/test_predictions.npz")
    assert list(expected["sources"]) == [r["source"] for r in rows]
    np.testing.assert_allclose(
        model.predict_proba(x), expected["probabilities"], atol=1e-12
    )
    output.mkdir(parents=True)
    target = output / "model.cbm"
    model.save_model(str(target))
    restored = CatBoostClassifier()
    restored.load_model(str(target))
    np.testing.assert_allclose(
        restored.predict_proba(x), expected["probabilities"], atol=1e-12
    )
    categories = {k: schema["categories"][k] for k in features[:4]}
    categories.update({k: ["양호", "주의"] for k in features[4:]})
    manifest = {
        "version": model_name,
        "features": features,
        "labels": schema["labels"],
        "categories": categories,
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "modelSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "schemaSha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "verifiedTestRows": len(rows),
        "trainingContract": {
            "analysisBundle": "skin-analysis-v4",
            "categories": "양호/주의",
            "threshold": 0.5,
            "scoreKind": "binary_caution_probability",
            "aggregation": "mean-cheeks-pore-tone-eyes-wrinkle-v1",
            "roiMethod": "occlusion_anchored_visible_roi_v2",
            "mobileEquivalenceValidated": False,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verifiedRows": len(rows), "bundle": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name", default="recommend-cat-v2")
    parser.add_argument("--output", type=Path, help="Default: ml/runs/<model-name>/bundle")
    parser.add_argument("--experiment", type=Path, default=EXPERIMENT)
    parser.add_argument("--schema", type=Path, default=SCHEMA)
    args = parser.parse_args()
    export(args.output, args.experiment, args.schema, args.model_name)
