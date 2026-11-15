import hashlib
import json

import pytest

from app.core.config import PROJECT_ROOT, Settings
from app.services.recommendation_v2_service import (
    FEATURES,
    SCORE_FEATURES,
    feature_values,
    load_bundle,
    predict_seeds,
    recommend_v2,
    target_goal,
)
from tests.test_recommendation_comparison import body, catalog, option


@pytest.mark.parametrize("goal", ["pores", "wrinkles", "pigmentation"])
def test_committed_v3_runs_without_training_artifacts(goal):
    bundle = PROJECT_ROOT / "ml/runs/recommend-cat-v3/bundle"
    assert Settings(_env_file=None).recommendation_bundle_path == bundle
    assert (bundle / "README.md").is_file()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    model_hash = hashlib.sha256((bundle / "model.cbm").read_bytes()).hexdigest()
    assert model_hash == manifest["modelSha256"]
    model, manifest = load_bundle(str(bundle))
    scores = dict.fromkeys(("pores", "wrinkles", "pigmentation"), 0.6)
    scores[goal] = 0.9
    request = body(scores=scores)
    assert target_goal(request) == goal
    seeds, info = predict_seeds(request, goal, str(bundle))
    assert info["version"] == "recommend-cat-v3"
    assert manifest["features"] == FEATURES + SCORE_FEATURES
    assert list(info["features"].values()) == feature_values(request, goal, manifest["features"])
    probabilities = model.predict_proba([list(info["features"].values())], thread_count=2)[0]
    assert len(probabilities) == 80
    indices = sorted(range(80), key=lambda i: (-probabilities[i], i))[:5]
    assert [seed["id"] for seed in seeds] == [manifest["labels"][i]["db_id"] for i in indices]
    candidates = [option(f"p{i}", [seed["id"]]) for i, seed in enumerate(seeds)]
    result = recommend_v2(
        request, goal, catalog(candidates), str(bundle), model_name="recommend-cat-v3"
    )
    assert result["status"] == "ok" and len(result["matches"]) == 5
    assert result["model"]["version"] == "recommend-cat-v3"
    assert len(result["model"]["features"]) == 10
    assert result["secondaryRecommendation"]["model"]["version"] == "recommend-cat-v3"
