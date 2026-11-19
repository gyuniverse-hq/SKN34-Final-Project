import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.ar_palette import FEATURES, score_inputs, shade_features, top_chips
from app.core.ar_palette_artifacts import load_palette_model, read_json, score_model, write_json
from app.schemas.ar_history import RankPalette
from app.services.ar_palette_service import ArPaletteService, experiment_arm, model_scores
from app.services.ar_palette_training_service import (
    summarize_experiment,
    synthetic_dataset,
    temporal_split,
    train_dataset,
)


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


def test_real_training_gate_and_synthetic_bundle(tmp_path):
    dataset = tmp_path / "data.json"
    synthetic_dataset(dataset)
    data = read_json(dataset)
    real = tmp_path / "real.json"
    write_json(
        real,
        {
            **data,
            "source": "db",
            "rows": [{**row, "policy_version": "ar1:-:-:rule"} for row in data["rows"]],
        },
    )
    assert train_dataset(real, tmp_path / "real-model")["status"] == "skipped"
    assert not (tmp_path / "real-model").exists()
    output = tmp_path / "candidate"
    report = train_dataset(dataset, output)
    assert report["status"] == "candidate_created" and report["offline_pass"] is None
    assert report["metrics"]["candidate_hit_at_1"] == 1.0
    model, version, source = load_palette_model(output, allow_synthetic=True)
    assert len(version) == 16 and source == "synthetic"
    scores = score_model(model, [r["features"] for r in data["rows"][-3:]])
    assert scores.index(max(scores)) == 1
    ranking_rows = [(("p", str(i)), row["features"], 0) for i, row in enumerate(data["rows"][-3:])]
    local = SimpleNamespace(env="local", ar_palette_model_dir=output)
    assert model_scores(local, ranking_rows) == (scores, f"s-{version}")
    with pytest.raises(ValueError, match="Incompatible"):
        load_palette_model(output)


def test_temporal_split_drops_earlier_rows_from_evaluation_sessions(tmp_path):
    path = tmp_path / "synthetic.json"
    synthetic_dataset(path)
    rows = read_json(path)["rows"]
    rows[0]["member"], rows[0]["session_id"] = rows[-1]["member"], rows[-1]["session_id"]
    dev, test, boundary = temporal_split(rows, 8)
    assert rows[0] not in dev and rows[0] not in test
    assert all(row["requested_at"] < boundary for row in dev)
    assert len({r["request_id"] for r in test}) == 8


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
        ar_palette_model_dir=None,
        ar_palette_data_dir=tmp_path,
    )
    result = asyncio.run(ArPaletteService(repo, config).rank(owner, body))
    assert repo.save_rank.await_args.args[4] == "ar1:trial:B:fallback"
    snapshot = read_json(tmp_path / "snapshots" / f"{body.request_id}.json")
    features = snapshot["features"][str(result.candidates[0].candidate_id)]
    assert set(features) == set(FEATURES) and features["rating_avg"] == 4.5
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
