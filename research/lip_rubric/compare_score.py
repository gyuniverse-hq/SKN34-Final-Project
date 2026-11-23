"""Score lip crops with a frozen encoder + Ridge (Astra absolute total) and compare pairs.

Default scorer is DINOv2-ViT-S/14 (best R5 holdout in the score bakeoff). Higher = more natural.
Absolute level is biased low vs R5 humans; use same-face before/after deltas.

  ml/.venv/Scripts/python.exe research/lip_rubric/compare_score.py pairs my_pairs.csv
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_score.py pairs my_pairs.csv --encoder resnet18
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_score.py pool-sanity --encoder dinov2_vits14
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from common import DATA, read_csv, write_csv
from learn_astra import (
    ENCODERS,
    OUT,
    POOL,
    _emb_map,
    _ridge,
    embedding_paths,
    load_astra,
    load_encoder,
)

STRONG = {"strong"}


def _summary_path(encoder: str) -> Path:
    return OUT / ("fit_summary.json" if encoder == "resnet18" else f"fit_summary_{encoder}.json")


def fit_head(encoder: str):
    """Ridge on Astra total; alpha from the saved score bakeoff summary."""
    summary = json.loads(_summary_path(encoder).read_text(encoding="utf8"))
    alpha = float(summary["targets"]["total"]["alpha"])
    astra = load_astra()
    a_path, _ = embedding_paths(encoder)
    emb = _emb_map(a_path)
    X = np.stack([emb[r["image_id"]] for r in astra])
    y = np.array([float(r["total"]) for r in astra])
    return _ridge(alpha).fit(X, y), alpha


def embed_paths(paths: list[str], encoder: str, device: str) -> np.ndarray:
    import torch
    from PIL import Image

    model, transform = load_encoder(encoder, device)
    vecs = []
    with torch.inference_mode():
        for path in paths:
            image = Image.open(path).convert("RGB")
            feat = model(transform(image).unsqueeze(0).to(device))[0].float().cpu().numpy()
            vecs.append(feat / (np.linalg.norm(feat) + 1e-9))
    return np.stack(vecs).astype(np.float32)


def score_paths(
    paths: list[str],
    encoder: str,
    device: str | None = None,
    *,
    calibrate: bool = True,
) -> tuple[np.ndarray, dict]:
    import torch

    from calibrate_score import apply_calibration

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    head, alpha = fit_head(encoder)
    feats = embed_paths(paths, encoder, device)
    raw = head.predict(feats)
    meta = {"encoder": encoder, "alpha": alpha, "device": device, "calibrated": False}
    if calibrate:
        cal, cal_meta = apply_calibration(raw, encoder)
        if cal_meta is not None:
            meta["calibrated"] = True
            meta["calibration"] = calib_path_name(encoder)
            meta["raw_mean"] = round(float(np.mean(raw)), 4)
            return cal, meta
    return raw, meta


def calib_path_name(encoder: str) -> str:
    from calibrate_score import calib_path

    return str(calib_path(encoder))


def compare_pairs(rows: list[dict], encoder: str, device: str | None = None) -> tuple[dict, list[dict]]:
    paths = [r["before_crop"] for r in rows] + [r["after_crop"] for r in rows]
    scores, meta = score_paths(paths, encoder, device)
    before, after = scores[: len(rows)], scores[len(rows) :]
    out_rows = []
    wins = ties = losses = 0
    for i, r in enumerate(rows):
        d = float(after[i] - before[i])
        verdict = "after" if d > 1e-4 else "before" if d < -1e-4 else "tie"
        wins += verdict == "after"
        losses += verdict == "before"
        ties += verdict == "tie"
        out_rows.append({
            **{k: r.get(k, "") for k in ("face_id", "label", "before_id", "after_id")},
            "before_score": round(float(before[i]), 4),
            "after_score": round(float(after[i]), 4),
            "delta": round(d, 4),
            "winner": verdict,
            "before_crop": r["before_crop"],
            "after_crop": r["after_crop"],
        })
    summary = {
        **meta,
        "n": len(rows),
        "after_wins": wins,
        "before_wins": losses,
        "ties": ties,
        "after_win_rate": round(wins / max(1, wins + losses), 4),
        "mean_delta_after_minus_before": round(float(np.mean(after - before)), 4),
        "mean_abs_delta": round(float(np.mean(np.abs(after - before))), 4),
    }
    return summary, out_rows


def pool_sanity(encoder: str, device: str | None = None) -> dict:
    key = {r["image_id"]: r for r in read_csv(POOL / "key.csv")}
    astra_ids = {r["image_id"] for r in read_csv(DATA / "astra" / "ratings.csv")}
    by_face = defaultdict(list)
    for iid in astra_ids:
        k = key.get(iid)
        if not k or k["kind"] != "render":
            continue
        by_face[k["face_id"]].append(k)
    pairs = []
    for face, items in by_face.items():
        currents = [x for x in items if x["variant"] == "current"]
        bad = [x for x in items if x["variant"] != "current" and x.get("level") in STRONG]
        if not currents or not bad:
            continue
        cur = currents[0]
        for b in bad:
            pairs.append({
                "face_id": face,
                "label": f"current_vs_{b['variant']}:{b['level']}",
                "before_id": b["image_id"],
                "after_id": cur["image_id"],
                "before_crop": str(POOL / "images" / f"{b['image_id']}_crop.png"),
                "after_crop": str(POOL / "images" / f"{cur['image_id']}_crop.png"),
            })
    summary, rows = compare_pairs(pairs, encoder, device)
    out = OUT / f"pool_sanity_{encoder}"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "pairs.csv", rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _add_scorer_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--encoder", choices=ENCODERS, default="dinov2_vits14")
    parser.add_argument("--device", default=None)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pairs")
    a.add_argument("csv", type=Path)
    a.add_argument("--out", type=Path)
    _add_scorer_flags(a)
    b = sub.add_parser("pool-sanity")
    _add_scorer_flags(b)
    c = sub.add_parser("score")
    c.add_argument("csv", type=Path)
    c.add_argument("--out", type=Path)
    _add_scorer_flags(c)
    args = p.parse_args(argv)

    if args.cmd == "pool-sanity":
        pool_sanity(args.encoder, args.device)
        return
    if args.cmd == "score":
        rows = read_csv(args.csv)
        scores, meta = score_paths([r["crop_path"] for r in rows], args.encoder, args.device, calibrate=True)
        out_rows = [{**r, "score": round(float(scores[i]), 4)} for i, r in enumerate(rows)]
        out = args.out or OUT / f"scores_{args.encoder}.csv"
        write_csv(out, out_rows)
        print(json.dumps({**meta, "n": len(out_rows), "mean": round(float(scores.mean()), 4), "out": str(out)}))
        return

    rows = read_csv(args.csv)
    summary, out_rows = compare_pairs(rows, args.encoder, args.device)
    out = Path(args.out) if args.out else OUT / f"compare_pairs_{args.encoder}"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "pairs.csv", out_rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
