import hashlib
import json
from unittest.mock import Mock, patch

import pytest

from app.services.recommendation_v2_service import (
    FEATURES,
    SCORE_FEATURES,
    feature_values,
    load_bundle,
    predict_seeds,
)
from tests.test_recommendation_comparison import body


def manifest(features):
    return {
        "version": "recommend-cat-v3",
        "modelSha256": "test-hash",
        "features": features,
        "numericFeatures": SCORE_FEATURES if len(features) == 10 else [],
        "labels": [{"db_id": i + 1, "name": str(i + 1)} for i in range(80)],
        "categories": dict(
            zip(FEATURES, [[v] for v in feature_values(body(), "pores")], strict=True)
        ),
        "trainingContract": {},
    }


def test_numeric_inputs_keep_the_training_order_and_raw_precision():
    request = body(scores={"pores": 0.9137, "pigmentation": 0.2742, "wrinkles": 0.6329})
    assert feature_values(request, "pores", FEATURES + SCORE_FEATURES) == [
        "30대", "여성", "지성", "모공케어", "주의", "주의", "양호",
        0.9137, 0.6329, 0.2742,
    ]
    assert len(feature_values(request, "pores")) == 7
    with pytest.raises(ValueError, match="invalid_model_features"):
        feature_values(request, "pores", FEATURES + SCORE_FEATURES[::-1])


@pytest.mark.parametrize("features", [FEATURES, FEATURES + SCORE_FEATURES])
def test_prediction_uses_the_selected_bundle_contract(features):
    model = Mock()
    model.predict_proba.return_value = [[i / 100 for i in range(80)]]
    with patch(
        "app.services.recommendation_v2_service.load_bundle",
        return_value=(model, manifest(features)),
    ):
        seeds, info = predict_seeds(body(), "pores", "unused")
    assert model.predict_proba.call_args.args[0] == [feature_values(body(), "pores", features)]
    assert [seed["id"] for seed in seeds] == [80, 79, 78, 77, 76]
    assert list(info["features"]) == features
    if len(features) == 10:
        assert info["features"]["pigmentation_score"] == 0.2


@pytest.mark.parametrize("features", [FEATURES, FEATURES + SCORE_FEATURES])
def test_loader_accepts_both_native_model_contracts(tmp_path, features):
    import catboost

    artifact = manifest(features)
    (tmp_path / "model.cbm").write_bytes(b"test-model")
    artifact["modelSha256"] = hashlib.sha256(b"test-model").hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(artifact), encoding="utf-8")
    model = Mock(feature_names_=[str(i) for i in range(len(features))])
    model.get_cat_feature_indices.return_value = list(range(7))
    with patch.object(catboost, "CatBoostClassifier", return_value=model):
        loaded, _ = load_bundle(str(tmp_path))
    assert loaded is model


@pytest.mark.parametrize("invalid", ["numeric_order", "model_width", "categorical_indices", "hash"])
def test_loader_rejects_mismatched_numeric_contract(tmp_path, invalid):
    import catboost

    artifact = manifest(FEATURES + SCORE_FEATURES)
    (tmp_path / "model.cbm").write_bytes(b"test-model")
    artifact["modelSha256"] = hashlib.sha256(b"test-model").hexdigest()
    if invalid == "numeric_order":
        artifact["numericFeatures"] = SCORE_FEATURES[::-1]
    if invalid == "hash":
        artifact["modelSha256"] = "wrong"
    (tmp_path / "manifest.json").write_text(json.dumps(artifact), encoding="utf-8")
    width = 7 if invalid == "model_width" else 10
    model = Mock(feature_names_=[str(i) for i in range(width)])
    model.get_cat_feature_indices.return_value = list(
        range(10 if invalid == "categorical_indices" else 7)
    )
    with (
        patch.object(catboost, "CatBoostClassifier", return_value=model),
        pytest.raises(ValueError, match="invalid_model"),
    ):
        load_bundle(str(tmp_path))
