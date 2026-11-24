"""Score lip crops with the fine-tuned EfficientNet-B0 and compare before/after pairs.

Uses research/data/lip_rubric/learn_astra/finetune_b0.pt (Astra labels, same-face ranking).
Higher score = more natural. Prefer same-face pairs; absolute level is biased low vs R5.

  # CSV with before_crop,after_crop[,face_id,label]
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pairs my_pairs.csv

  # Sanity: same-face current vs strong defects in the openai pool (Astra-scored faces)
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pool-sanity

  # Score a folder of crops listed in a CSV (image_id,crop_path)
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py score crops.csv
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from common import DATA, read_csv, write_csv
from finetune_astra import OUT, build_model, load_images, predict
from learn_astra import POOL

WEIGHTS = OUT / "finetune_b0.pt"
STRONG = {"strong"}


def load_scorer(device: str | None = None):
    import torch

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model()
    state = torch.load(WEIGHTS, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.to(device).eval()
    return model, device


def score_paths(model, device, paths: list[str]) -> np.ndarray:
    return predict(model, load_images(paths), device)


def compare_pairs(rows: list[dict], device: str | None = None) -> dict:
    model, device = load_scorer(device)
    before = score_paths(model, device, [r["before_crop"] for r in rows])
    after = score_paths(model, device, [r["after_crop"] for r in rows])
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
        "n": len(rows),
        "after_wins": wins,
        "before_wins": losses,
        "ties": ties,
        "after_win_rate": round(wins / max(1, wins + losses), 4),
        "mean_delta_after_minus_before": round(float(np.mean(after - before)), 4),
        "weights": str(WEIGHTS),
    }
    return summary, out_rows


def pool_sanity(device: str | None = None) -> dict:
    """current should beat same-face strong defects on the openai pool."""
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
    summary, rows = compare_pairs(pairs, device)
    by_defect = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        name = r["label"].split("current_vs_", 1)[-1]
        if r["winner"] == "after":
            by_defect[name][0] += 1
        elif r["winner"] == "before":
            by_defect[name][1] += 1
        else:
            by_defect[name][2] += 1
    summary["by_defect"] = {
        k: {"current_wins": v[0], "defect_wins": v[1], "ties": v[2],
            "current_win_rate": round(v[0] / max(1, v[0] + v[1]), 4)}
        for k, v in sorted(by_defect.items())
    }
    out = OUT / "pool_sanity_b0"
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "pairs.csv", rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pairs"); a.add_argument("csv", type=Path); a.add_argument("--out", type=Path)
    a.add_argument("--device", default=None)
    b = sub.add_parser("pool-sanity"); b.add_argument("--device", default=None)
    c = sub.add_parser("score"); c.add_argument("csv", type=Path); c.add_argument("--out", type=Path)
    c.add_argument("--device", default=None)
    args = p.parse_args(argv)

    if args.cmd == "pool-sanity":
        pool_sanity(args.device)
        return
    if args.cmd == "score":
        model, device = load_scorer(args.device)
        rows = read_csv(args.csv)
        scores = score_paths(model, device, [r["crop_path"] for r in rows])
        out_rows = [{**r, "score": round(float(scores[i]), 4)} for i, r in enumerate(rows)]
        out = args.out or OUT / "scores.csv"
        write_csv(out, out_rows)
        print(json.dumps({"n": len(out_rows), "mean": round(float(scores.mean()), 4), "out": str(out)}))
        return

    rows = read_csv(args.csv)
    summary, out_rows = compare_pairs(rows, args.device)
    out = args.out or OUT / "compare_pairs"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "pairs.csv", out_rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
