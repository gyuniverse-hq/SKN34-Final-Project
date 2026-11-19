import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.ar_palette import CATEGORICAL, FEATURE_VERSION, FEATURES


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, sort_keys=True, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf8"))


def feature_matrix(rows):
    return [[float("nan") if row[name] is None else row[name] for name in FEATURES] for row in rows]


def score_model(model, rows):
    if not rows:
        return []
    scores = list(model.predict_proba(feature_matrix(rows), thread_count=2)[:, 1])
    if len(scores) != len(rows) or not all(math.isfinite(s) for s in scores):
        raise ValueError("Invalid AR model scores")
    return scores


@lru_cache(maxsize=4)
def load_palette_model(directory: Path, *, allow_synthetic=False, require_offline_pass=False):
    from catboost import CatBoostClassifier

    manifest = read_json(directory / "manifest.json")
    model_file = directory / "model.cbm"
    digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
    if (
        manifest["feature_version"] != FEATURE_VERSION
        or tuple(manifest["features"]) != FEATURES
        or tuple(manifest["categorical"]) != CATEGORICAL
        or manifest["model_sha256"] != digest
        or manifest["source"] not in ("db", "synthetic")
        or (manifest["source"] == "synthetic" and not allow_synthetic)
        or (require_offline_pass and manifest.get("offline_pass") is not True)
    ):
        raise ValueError("Incompatible AR model bundle")
    model = CatBoostClassifier()
    model.load_model(str(model_file))
    if tuple(model.feature_names_) != FEATURES:
        raise ValueError("Unexpected AR model input columns")
    return model, digest[:16], manifest["source"]
