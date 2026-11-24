"""Smoke tests for the lip learner fit loop (synthetic embeddings, no network)."""
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from learn import fit_models  # noqa: E402


@pytest.fixture
def tiny_learn(tmp_path, monkeypatch):
    # Minimal CSV/DB shape for export is heavy; unit-test fit on synthetic embeddings instead.
    out = tmp_path / "learn"
    out.mkdir()
    monkeypatch.setattr("learn.OUT", out)

    faces = [f"f{i}" for i in range(6)]
    ids = []
    abs_rows = []
    rng = np.random.default_rng(0)
    emb = {}
    for i, face in enumerate(faces):
        for j in range(3):
            iid = f"{face}_{j}"
            ids.append(iid)
            # score strongly correlated with first dims
            total = float(j)
            vec = rng.normal(size=32).astype(np.float32) * 0.05
            vec[0] = total
            vec[1] = total * 0.5
            vec = vec / (np.linalg.norm(vec) + 1e-9)
            emb[iid] = vec
            abs_rows.append(
                {
                    "image_id": iid,
                    "face_id": face,
                    "pack": "t",
                    "kind": "render",
                    "finish": "satin",
                    "split": "pool",
                    "total": total,
                    "crop_path": str(tmp_path / f"{iid}.png"),
                }
            )
    pairs = []
    for i, face in enumerate(faces):
        high, low = f"{face}_2", f"{face}_0"
        # alternate side so both classes appear in every fold
        left, right = (high, low) if i % 2 == 0 else (low, high)
        pref = 1.0 if left == high else 0.0
        pairs.append(
            {
                "pair_id": f"p_{face}",
                "face_id": face,
                "split": "pool",
                "left": left,
                "right": right,
                "pref_left": pref,
                "left_crop": "",
                "right_crop": "",
            }
        )
    from common import write_csv

    write_csv(out / "labels_absolute.csv", abs_rows)
    write_csv(out / "pairs.csv", pairs)
    np.savez_compressed(
        out / "embeddings.npz",
        image_ids=np.array(list(emb)),
        embeddings=np.stack([emb[i] for i in emb]),
        encoder="toy",
        dim=32,
    )
    return out


def test_fit_on_synthetic(tiny_learn):
    summary = fit_models(n_splits=3)
    assert summary["absolute"]["n_images"] == 18
    assert summary["pairwise"]["n_pairs_used"] == 6
    assert summary["absolute"]["cv_spearman"] > 0.5
    assert summary["pairwise"]["cv_accuracy"] >= 0.5
    assert (tiny_learn / "fit_summary.json").exists()
