"""Calibrate frozen-encoder + Ridge scores onto the R5 human total scale.

Fits an isotonic map (monotone) from model → human using R5 checklist labels, so
absolute numbers can be compared to the human pass line (~4.68). Ranking is preserved.

  ml/.venv/Scripts/python.exe research/lip_rubric/calibrate_score.py
  ml/.venv/Scripts/python.exe research/lip_rubric/calibrate_score.py --encoder dinov2_vits14
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from common import read_csv, write_csv
from learn import OUT as R5_OUT
from learn import SEED, _emb_map, _group_folds
from learn_astra import ENCODERS, OUT, _ridge, _spearman, embedding_paths, load_astra

CALIB_NAME = "calibration_{encoder}.json"


def calib_path(encoder: str) -> Path:
    return OUT / CALIB_NAME.format(encoder=encoder)


def raw_predict_r5(encoder: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    summary = json.loads(
        (OUT / ("fit_summary.json" if encoder == "resnet18" else f"fit_summary_{encoder}.json")).read_text(
            encoding="utf8"
        )
    )
    alpha = float(summary["targets"]["total"]["alpha"])
    astra = load_astra()
    a_path, r_path = embedding_paths(encoder)
    a_emb, r_emb = _emb_map(a_path), _emb_map(r_path)
    r5 = read_csv(R5_OUT / "labels_absolute.csv")
    head = _ridge(alpha).fit(
        np.stack([a_emb[r["image_id"]] for r in astra]),
        np.array([float(r["total"]) for r in astra]),
    )
    raw = head.predict(np.stack([r_emb[r["image_id"]] for r in r5]))
    y = np.array([float(r["total"]) for r in r5])
    faces = np.array([r["face_id"] for r in r5])
    kinds = np.array([r["kind"] for r in r5])
    return raw, y, faces, kinds, alpha


def _metrics(y, p, faces, kinds) -> dict:
    render = kinds == "render"
    by_kind = {}
    for k in sorted(set(kinds.tolist())):
        m = kinds == k
        by_kind[k] = {
            "n": int(m.sum()),
            "human_mean": round(float(y[m].mean()), 4),
            "pred_mean": round(float(p[m].mean()), 4),
            "mae": round(float(np.mean(np.abs(y[m] - p[m]))), 4),
        }
    return {
        "spearman": _spearman(y, p),
        "mae": round(float(np.mean(np.abs(y - p))), 4),
        "bias_pred_minus_human": round(float((p - y).mean()), 4),
        "pred_mean": round(float(p.mean()), 4),
        "pred_std": round(float(p.std()), 4),
        "human_mean": round(float(y.mean()), 4),
        "human_std": round(float(y.std()), 4),
        "render_spearman": _spearman(y[render], p[render]),
        "by_kind": by_kind,
    }


def fit_isotonic(raw: np.ndarray, y: np.ndarray):
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=0.0, y_max=5.0, out_of_bounds="clip", increasing=True)
    iso.fit(raw, y)
    return iso


def apply_isotonic(iso, raw: np.ndarray) -> np.ndarray:
    return np.asarray(iso.predict(raw), dtype=np.float64)


def isotonic_to_dict(iso) -> dict:
    return {
        "type": "isotonic",
        "x_thresholds": [float(x) for x in iso.X_thresholds_],
        "y_thresholds": [float(y) for y in iso.y_thresholds_],
        "y_min": 0.0,
        "y_max": 5.0,
    }


def isotonic_from_dict(data: dict):
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=data["y_min"], y_max=data["y_max"], out_of_bounds="clip", increasing=True)
    # Reconstruct by fitting on threshold knots (exact for piecewise-constant isotonic).
    iso.fit(np.array(data["x_thresholds"]), np.array(data["y_thresholds"]))
    return iso


def load_calibrator(encoder: str):
    path = calib_path(encoder)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("type") != "isotonic":
        raise ValueError(f"unsupported calibrator type: {data.get('type')}")
    return isotonic_from_dict(data), data


def apply_calibration(raw_scores: np.ndarray, encoder: str) -> tuple[np.ndarray, dict | None]:
    loaded = load_calibrator(encoder)
    if loaded is None:
        return np.asarray(raw_scores, dtype=np.float64), None
    iso, meta = loaded
    cal = np.clip(apply_isotonic(iso, np.asarray(raw_scores, dtype=np.float64)), 0.0, 5.0)
    return cal, meta


def group_cv_mae(raw, y, faces, n_splits=5) -> float:
    folds, _ = _group_folds(faces.tolist(), n_splits, SEED)
    errs = []
    for tr, te in folds:
        if len(te) == 0 or len(tr) < 5:
            continue
        iso = fit_isotonic(raw[tr], y[tr])
        pred = apply_isotonic(iso, raw[te])
        errs.append(np.mean(np.abs(y[te] - pred)))
    return float(np.mean(errs)) if errs else float("nan")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--encoder", choices=ENCODERS, default="dinov2_vits14")
    args = p.parse_args(argv)

    raw, y, faces, kinds, alpha = raw_predict_r5(args.encoder)
    before = _metrics(y, raw, faces, kinds)
    cv_mae = group_cv_mae(raw, y, faces)

    iso = fit_isotonic(raw, y)
    cal = apply_isotonic(iso, raw)
    after = _metrics(y, cal, faces, kinds)

    payload = {
        **isotonic_to_dict(iso),
        "encoder": args.encoder,
        "ridge_alpha": alpha,
        "n_r5": int(len(y)),
        "pass_line_active": None,
        "before": before,
        "after_fit_on_all_r5": after,
        "group_cv_mae_calibrated": round(cv_mae, 4),
        "note": (
            "Isotonic map fit on all R5 for deployment; group_cv_mae_calibrated is the honest "
            "estimate. after_fit_on_all_r5 is optimistic. Use calibrated_score vs human pass line."
        ),
    }
    anchors = OUT / "pass_gallery" / "pass_anchors.json"
    if anchors.is_file():
        payload["pass_line_active"] = float(json.loads(anchors.read_text(encoding="utf8"))["pass_line_active"])

    out = calib_path(args.encoder)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")

    points = []
    r5 = read_csv(R5_OUT / "labels_absolute.csv")
    for i, r in enumerate(r5):
        points.append({
            "image_id": r["image_id"],
            "kind": r["kind"],
            "human_total": round(float(y[i]), 4),
            "model_raw": round(float(raw[i]), 4),
            "model_calibrated": round(float(cal[i]), 4),
        })
    write_csv(OUT / f"calibration_points_{args.encoder}.csv", points)

    print(json.dumps({
        "out": str(out),
        "before": before,
        "after_fit_on_all_r5": after,
        "group_cv_mae_calibrated": round(cv_mae, 4),
        "pass_line_active": payload["pass_line_active"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
