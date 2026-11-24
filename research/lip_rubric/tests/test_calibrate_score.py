"""Calibration helpers without requiring embeddings on disk beyond what's already there."""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from calibrate_score import apply_isotonic, fit_isotonic, isotonic_from_dict, isotonic_to_dict  # noqa: E402


def test_isotonic_roundtrip_and_monotone():
    raw = np.array([1.0, 1.5, 2.0, 2.5, 3.0])
    y = np.array([0.5, 2.0, 3.0, 4.0, 5.0])
    iso = fit_isotonic(raw, y)
    pred = apply_isotonic(iso, raw)
    assert np.all(np.diff(pred) >= -1e-9)
    data = isotonic_to_dict(iso)
    iso2 = isotonic_from_dict(data)
    pred2 = apply_isotonic(iso2, raw)
    assert np.allclose(pred, pred2, atol=1e-5)


def test_calib_file_schema_if_present():
    from calibrate_score import calib_path

    path = calib_path("dinov2_vits14")
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf8"))
    assert data["type"] == "isotonic"
    assert len(data["x_thresholds"]) == len(data["y_thresholds"])
