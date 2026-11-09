"""Score extracted makeup recipes against human-labelled ones (plan step 4).

    python research/recipe_eval/score_recipes.py --pred backend/api/seed/source/look_recipe_review.json \
        --gold research/recipe_eval/gold.json [--tolerance 10] [--out report.json]

Pred is the review file written by app.jobs.extract_look_recipe. Gold is a list of
    {"videoId": "...", "steps": [{"zone": "contour", "startSeconds": 32, "style": "jawline"}, ...]}
in the order the steps are applied; style and startSeconds are optional. Only video ids present in both are scored.

Metrics (per video, then the mean over videos; no pass line is set before numbers exist):
- zone precision / recall / F1 over the set of zones
- order: longest common subsequence of the zone sequences / the longer sequence (1 = same order)
- time: share of matched zones whose start is within --tolerance seconds (only where both give a start)
- style: share of matched zones with a gold style where the predicted style is the same
  (a missing predicted style counts as wrong, because the app then draws the default shape)

YouMakeup (AIM3-RUC/YouMakeup) needs a signed license form before download and its schema is not on the repo page,
so a converter from its step annotations to the gold format has to be written once the files are in hand.
Nothing here sends anything anywhere.
"""

import argparse
import json
from pathlib import Path


def lcs_len(a: list[str], b: list[str]) -> int:
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            table[i][j] = table[i - 1][j - 1] + 1 if x == y else max(table[i - 1][j], table[i][j - 1])
    return table[-1][-1]


def first_by_zone(steps: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for step in steps:
        out.setdefault(step["zone"], step)
    return out


def score_video(pred_steps: list[dict], gold_steps: list[dict], tolerance: float) -> dict:
    pred, gold = first_by_zone(pred_steps), first_by_zone(gold_steps)
    hit = set(pred) & set(gold)
    precision = len(hit) / len(pred) if pred else 0.0
    recall = len(hit) / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    pred_order = [s["zone"] for s in pred.values()]
    gold_order = [s["zone"] for s in gold.values()]
    longest = max(len(pred_order), len(gold_order))
    order = lcs_len(pred_order, gold_order) / longest if longest else 1.0
    timed = [z for z in hit if pred[z].get("startSeconds") is not None and gold[z].get("startSeconds") is not None]
    time_hit = sum(abs(pred[z]["startSeconds"] - gold[z]["startSeconds"]) <= tolerance for z in timed)
    styled = [z for z in hit if gold[z].get("style")]
    style_hit = sum(pred[z].get("style") == gold[z]["style"] for z in styled)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "order": order,
        "time": time_hit / len(timed) if timed else None,
        "style": style_hit / len(styled) if styled else None,
        "zones_matched": len(hit),
        "zones_pred": len(pred),
        "zones_gold": len(gold),
        "timed_pairs": len(timed),
        "styled_pairs": len(styled),
    }


def mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def score(pred_entries: list[dict], gold_entries: list[dict], tolerance: float = 10) -> dict:
    pred = {e["videoId"] if "videoId" in e else e["video_id"]: e for e in pred_entries}
    gold = {e["videoId"]: e for e in gold_entries}
    videos = {}
    for video_id in sorted(set(pred) & set(gold)):
        steps = [
            {
                "zone": s["zone"],
                "startSeconds": s.get("start_seconds", s.get("startSeconds")),
                "style": s.get("style"),
            }
            for s in pred[video_id]["recipe"]["steps"]
        ]
        videos[video_id] = score_video(steps, gold[video_id]["steps"], tolerance)
    keys = ("precision", "recall", "f1", "order", "time", "style")
    return {
        "videos_scored": len(videos),
        "videos_missing_in_pred": sorted(set(gold) - set(pred)),
        "mean": {k: mean([v[k] for v in videos.values()]) for k in keys},
        "per_video": videos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = score(
        json.loads(args.pred.read_text(encoding="utf-8")),
        json.loads(args.gold.read_text(encoding="utf-8")),
        args.tolerance,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
