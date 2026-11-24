import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.ar_palette import FEATURES, score_inputs, shade_features, top_chips
from app.core.ar_palette_artifacts import (
    CLASSIFIER,
    RANKER,
    load_palette_model,
    read_json,
    score_model,
    write_json,
)
from app.schemas.ar_history import RankPalette
from app.services import ar_palette_search
from app.services.ar_palette_service import ArPaletteService, experiment_arm, model_scores
from app.services.ar_palette_training_service import (
    mixed_label_requests,
    ranked_comparison,
    summarize_experiment,
    synthetic_dataset,
    temporal_split,
    train_dataset,
)


@pytest.fixture
def short_search(monkeypatch):
    grid = {
        "iterations": (8, 12),
        "depth": (3, 4),
        "learning_rate": (0.08, 0.12),
        "l2_leaf_reg": (3.0,),
    }
    monkeypatch.setattr(ar_palette_search, "GRID_SPACE", grid)
    monkeypatch.setattr(ar_palette_search, "SEARCH_SPACE", {**grid, "iterations": (8, 12, 16)})


def test_features_use_unique_daily_history_and_preserve_crop_and_product_diversity():
    catalog = {
        ("a", "r"): shade_features("#F34817", "matte", "estimated", None),
        ("a", "p"): shade_features("#C26471", "matte", "estimated", None),
        ("b", "n"): shade_features("#C2ACA8", "glossy", "estimated", None),
    }
    assert shade_features("#F34817", "matte", "placeholder", None) is None
    rows, personalized = score_inputs(
        "lip",
        list(catalog),
        catalog,
        {"a": (4.7, 30), "b": (4.5, 20)},
        [(("a", "r"), date(2026, 11, 1), 3.0), (("missing", "old"), date(2026, 11, 2), 1.0)],
    )
    first = rows[0][1]
    assert tuple(first) == FEATURES and personalized
    assert first["prior_activity_count_90d"] == 2
    assert first["prior_same_family_share_90d"] == 1.0
    assert first["prior_same_texture_share_90d"] == 1.0
    assert [row[0] for row in top_chips(rows, [0.9, 0.8, 0.6], personalized)] == [
        ("a", "r"),
        ("b", "n"),
    ]
    cold, _ = score_inputs("lip", list(catalog), catalog, {"a": (4.7, 30)}, [])
    assert cold[0][1]["prior_activity_count_90d"] == 0
    assert cold[0][1]["prior_same_family_share_90d"] is None


def test_training_waits_until_30_days_of_observations_have_closed(tmp_path, short_search):
    dataset = tmp_path / "data.json"
    synthetic_dataset(dataset)
    data = read_json(dataset)
    real = tmp_path / "real.json"
    payload = {
        **data,
        "source": "db",
        "label_window_seconds": 86_400,
        "receipt_grace_seconds": 86_400,
        "rows": [{**row, "policy_version": "ar1:-:-:rule"} for row in data["rows"][:90]],
    }
    first = datetime.fromisoformat(payload["rows"][0]["requested_at"])
    payload["as_of"] = (first + timedelta(days=31)).isoformat()
    write_json(real, payload)
    output = tmp_path / "real-model"
    early = train_dataset(real, output)
    assert early["reason"] == "insufficient_collection_days"
    assert early["collection_days"] == 29 and not output.exists()
    payload["as_of"] = (first + timedelta(days=32)).isoformat()
    write_json(real, payload)
    ready = train_dataset(real, output, search_method="grid")
    assert ready["status"] == "candidate_created" and ready["collection_days"] == 30
    assert ready["development"]["positive_requests"] == 21


def test_compare_searches_and_reuse_winning_method_from_baseline(tmp_path, short_search):
    dataset = tmp_path / "data.json"
    synthetic_dataset(dataset)
    data = read_json(dataset)
    output = tmp_path / "candidate"
    report = train_dataset(dataset, output, model_type=CLASSIFIER)
    assert report["status"] == "candidate_created" and report["offline_pass"] is None
    assert report["metrics"]["candidate_hit_at_1"] == 1.0
    search = report["search"]
    assert set(search["results"]) == {"grid", "random", "optuna"}
    for method in search["results"].values():
        assert len(method["trials"]) == search["trials_per_method"] == 8
        assert len({tuple(t["parameters"].values()) for t in method["trials"]}) == 8
    manifest = read_json(output / "manifest.json")
    assert manifest.pop("model_type") == CLASSIFIER
    write_json(output / "manifest.json", manifest)
    assert manifest["parameters"]["auto_class_weights"] == "Balanced"
    assert manifest["search"]["method"] == search["method"]
    model, version, source = load_palette_model(output, allow_synthetic=True)
    assert len(version) == 16 and source == "synthetic"
    scores = score_model(model, [r["features"] for r in data["rows"][-3:]])
    assert scores.index(max(scores)) == 1
    ranking_rows = [(("p", str(i)), row["features"], 0) for i, row in enumerate(data["rows"][-3:])]
    local = SimpleNamespace(env="local", ar_palette_model_dir=output)
    assert model_scores(local, ranking_rows) == (scores, f"s-{version}")
    with pytest.raises(ValueError, match="Incompatible"):
        load_palette_model(output)
    refresh = train_dataset(dataset, tmp_path / "refresh", baseline=output, model_type=CLASSIFIER)
    assert refresh["search"]["requested_method"] == search["method"]
    assert set(refresh["search"]["results"]) == {search["method"]}


def test_default_pairlogit_bundle_can_serve_the_experiment_arm(tmp_path, short_search):
    dataset = tmp_path / "data.json"
    synthetic_dataset(dataset)
    output = tmp_path / "ranker"
    report = train_dataset(dataset, output, min_ndcg=0.9, min_lift=0.1)
    manifest = read_json(output / "manifest.json")
    assert report["offline_pass"] is True and report["decision_metric"] == "ndcg_at_3"
    assert report["metrics"]["candidate_ndcg_at_3"] == 1.0
    assert report["metrics"]["baseline_ndcg_at_3"] == pytest.approx(0.63093)
    assert report["search"]["objective"] == "mixed_label_request_ndcg_at_3"
    assert set(report["search"]["results"]) == {"random"}
    assert report["search"]["trials_per_method"] == 8
    assert (
        manifest["model_type"] == RANKER and manifest["parameters"]["loss_function"] == "PairLogit"
    )
    assert manifest["search"]["best_validation_ndcg_at_3"] == 1.0
    model, version, _ = load_palette_model(output, allow_synthetic=True, require_offline_pass=True)
    scores = score_model(model, [row["features"] for row in read_json(dataset)["rows"][-3:]])
    assert scores.index(max(scores)) == 1

    body = RankPalette(
        request_id=uuid4(),
        session_id=uuid4(),
        makeup_zone="lip",
        shades=[{"productId": "p", "shadeId": "s"}],
    )
    owner = next(str(i) for i in range(100) if experiment_arm("trial", str(i)) == "B")
    repo = SimpleNamespace(
        lock_rank=AsyncMock(return_value=None),
        ranking_inputs=AsyncMock(
            return_value=(
                {("p", "s"): ("#C26471", "matte", "estimated", None)},
                {"p": (4.5, 100)},
                [],
            )
        ),
        save_rank=AsyncMock(),
    )
    config = SimpleNamespace(
        env="local",
        ar_palette_mode="experiment",
        ar_palette_experiment="trial",
        cart_recommendation_experiment="",
        ar_palette_model_dir=output,
        ar_palette_data_dir=tmp_path,
    )
    result = asyncio.run(ArPaletteService(repo, config).rank(owner, body))
    assert result.candidates[0].shade_id == "s"
    assert repo.save_rank.await_args.args[3:5] == ("ml", f"ar1:trial:B:s-{version}")
    assert repo.save_rank.await_args.kwargs["cart_candidates"] is None


def test_pairlogit_skips_when_training_labels_have_no_within_request_pairs(tmp_path):
    dataset = tmp_path / "data.json"
    synthetic_dataset(dataset)
    data = read_json(dataset)
    development, _, _, _ = temporal_split(data["rows"])
    for row in development:
        row["added_to_cart"] = int(row["request_id"] == "demo-0")
    write_json(dataset, data)
    output = tmp_path / "ranker"
    report = train_dataset(dataset, output)
    assert report["reason"] == "insufficient_split_classes_or_comparable_requests"
    assert not output.exists()


def test_temporal_split_drops_earlier_rows_from_evaluation_sessions(tmp_path):
    path = tmp_path / "synthetic.json"
    synthetic_dataset(path)
    rows = read_json(path)["rows"]
    for row in rows[:3]:
        row["member"], row["session_id"] = rows[-1]["member"], rows[-1]["session_id"]
    dev, validation, test, cutoffs = temporal_split(rows)
    assert all(row not in dev + validation + test for row in rows[:3])
    assert all(row["requested_at"] < cutoffs["validation"] for row in dev)
    assert all(cutoffs["validation"] <= r["requested_at"] < cutoffs["test"] for r in validation)
    assert all(row["requested_at"] >= cutoffs["test"] for row in test)
    assert [len({r["request_id"] for r in part}) for part in (dev, validation, test)] == [24, 5, 6]


def test_repeat_impressions_keep_the_candidate_label_and_need_distinct_options():
    first = {
        "request_id": "request",
        "rank": 1,
        "member": "member",
        "features": {"makeup_zone": "lip"},
    }
    latest = {**first, "impression_id": "b", "added_to_cart": 1}
    earlier = {**first, "impression_id": "a", "added_to_cart": 0}
    other = {**first, "rank": 2, "impression_id": "c", "added_to_cart": 0}
    assert not mixed_label_requests([earlier, latest])
    assert mixed_label_requests([earlier, latest, other]) == {"request"}
    with patch(
        "app.services.ar_palette_training_service.score_model", return_value=[0.9, 0.9, 0.2]
    ):
        result = ranked_comparison([earlier, latest, other], object())
    assert result["baseline_hit_at_1"] == result["candidate_hit_at_1"] == 1.0
    assert result["baseline_ndcg_at_3"] == result["candidate_ndcg_at_3"] == 1.0


def test_rank_persists_assigned_arm_and_fallback_with_the_exact_features(tmp_path):
    body = RankPalette(
        request_id=uuid4(),
        session_id=uuid4(),
        makeup_zone="lip",
        shades=[{"productId": "p", "shadeId": "s"}],
    )
    owner = next(str(i) for i in range(100) if experiment_arm("trial", str(i)) == "B")
    repo = SimpleNamespace(
        lock_rank=AsyncMock(return_value=None),
        ranking_inputs=AsyncMock(
            return_value=(
                {("p", "s"): ("#C26471", "matte", "estimated", None)},
                {"p": (4.5, 100)},
                [],
            )
        ),
        save_rank=AsyncMock(),
    )
    config = SimpleNamespace(
        ar_palette_mode="experiment",
        ar_palette_experiment="trial",
        cart_recommendation_experiment="cart-trial",
        ar_palette_model_dir=None,
        ar_palette_data_dir=tmp_path,
    )
    result = asyncio.run(ArPaletteService(repo, config).rank(owner, body))
    assert repo.save_rank.await_args.args[4] == "ar1:trial:B:fallback"
    snapshot = read_json(tmp_path / "snapshots" / f"{body.request_id}.json")
    features = snapshot["features"][str(result.candidates[0].candidate_id)]
    assert set(features) == set(FEATURES) and features["rating_avg"] == 4.5
    assert repo.save_rank.await_args.kwargs["cart_candidates"] == []
    report = summarize_experiment(
        [
            {
                "arm": "A",
                "member_id": "a",
                "added_to_cart": True,
                "fallback": False,
                "empty": False,
            },
            {
                "arm": "B",
                "member_id": "b",
                "added_to_cart": False,
                "fallback": True,
                "empty": False,
            },
        ]
    )
    assert report["arms"]["B"]["sessions"] == report["arms"]["B"]["fallback_sessions"] == 1
    assert report["lift"] == -1 and report["result"] == "pending"


@pytest.mark.parametrize(
    ("baseline_rule", "baseline_versions", "candidate_versions", "result"),
    [
        pytest.param(True, [], ["m-B"], "passed", id="rule-baseline"),
        pytest.param(False, ["m-A"], ["m-B"], "passed", id="ml-baseline"),
        pytest.param(False, [], ["m-B"], "pending", id="fallback-only-baseline"),
        pytest.param(True, ["m-A"], ["m-B"], "pending", id="mixed-baseline"),
        pytest.param(False, ["m-A"], ["m-A"], "pending", id="same-model"),
        pytest.param(True, [], ["s-B"], "pending", id="synthetic-candidate"),
    ],
)
def test_experiment_uses_session_purchase_lift_for_valid_arms(
    baseline_rule, baseline_versions, candidate_versions, result
):
    versions = {"A": baseline_versions, "B": candidate_versions}
    rows = [
        {
            "arm": arm,
            "member_id": f"{arm}-{member}",
            "added_to_cart": arm == "B" or session == 0,
            "purchased": session < (1 if arm == "A" else 2),
            "served_rule": arm == "A" and baseline_rule,
            "fallback": arm == "A" and not (baseline_rule or baseline_versions),
            "empty": False,
            "model_versions": versions[arm],
        }
        for arm in ("A", "B")
        for member in range(3)
        for session in range(3)
    ]
    options = dict(min_sessions=9, min_lift=0.01)
    report = summarize_experiment(rows, finished=True, measure_purchase=True, **options)
    assert report["purchase_metrics"]["cart_to_purchase_lift"] == pytest.approx(-1 / 3)
    assert report["purchase_metrics"]["session_to_purchase_lift"] == pytest.approx(1 / 3)
    assert report["decision_metric"] == "session_to_purchase_rate"
    assert report["result"] == result
    unfinished = summarize_experiment(rows, finished=False, measure_purchase=True, **options)
    assert unfinished["result"] == "pending"
    without_purchases = summarize_experiment(rows, finished=True, **options)
    assert without_purchases["lift"] > 0
    assert without_purchases["purchase_metrics"] == "unmeasured"
    assert without_purchases["result"] == "pending"
