"""load_astra joins pool key metadata and applies the matte NA rule (no images, no network)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import learn_astra  # noqa: E402
from common import checks, load_json, write_csv  # noqa: E402


def _ratings_row(image_id, value):
    ids = [c["id"] for c in checks(load_json(HERE / "rubric.json"))]
    return {"image_id": image_id, **{c: value for c in ids}, "overall": 3}


@pytest.fixture
def pool(tmp_path, monkeypatch):
    astra, pool = tmp_path / "astra", tmp_path / "pool"
    monkeypatch.setattr(learn_astra, "ASTRA", astra)
    monkeypatch.setattr(learn_astra, "POOL", pool)
    key = [
        {"image_id": "m", "face_id": "f1", "kind": "render", "finish": "matte", "variant": "current", "human_label": "bare"},
        {"image_id": "g", "face_id": "f2", "kind": "render", "finish": "glossy", "variant": "texture_loss", "human_label": "unreviewed"},
    ]
    write_csv(pool / "key.csv", key)
    return astra


def test_matte_gloss_checks_become_na(pool):
    row = _ratings_row("m", 1)
    row.update({"q3_2": 0, "q3_3": 0, "q3_4": 0})
    write_csv(pool / "ratings.csv", [row, _ratings_row("g", 1)])
    rows = {r["image_id"]: r for r in learn_astra.load_astra()}
    assert rows["m"]["total"] == 5.0
    assert rows["g"]["total"] == 5.0
    assert rows["m"]["face_id"] == "f1" and rows["g"]["variant"] == "texture_loss"


def test_unknown_image_is_rejected(pool):
    write_csv(pool / "ratings.csv", [_ratings_row("missing", 1)])
    with pytest.raises(ValueError):
        learn_astra.load_astra()
