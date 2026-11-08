"""Summarize blinded rating CSV files with Wilson 95% intervals (ties excluded).

Input: one or more CSV downloads from rating/index.html.
Output: JSON to stdout; evaluator identities are random browser session IDs.
Run: python research/ar_model_compare/analyze_rating.py path/to/rating.csv [...]
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    groups = defaultdict(list)
    for file in args.files:
        with file.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("winner") not in ("current", "tie", row.get("candidate")) or not row.get("evaluator_id"):
                    raise ValueError(f"invalid row in {file}")
                groups[row["candidate"]].append(row)
    out = {}
    for candidate, rows in groups.items():
        wins = sum(r["winner"] == candidate for r in rows)
        losses = sum(r["winner"] == "current" for r in rows)
        n = wins + losses
        if n:
            z = 1.959963984540054; p = wins / n; den = 1 + z*z/n
            center = (p + z*z/(2*n)) / den
            half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
            interval = [center-half, center+half]
        else:
            p = interval = None
        out[candidate] = {"wins": wins, "losses": losses, "ties": len(rows)-n,
                          "candidate_win_rate": p, "wilson_95": interval,
                          "evaluators": len({r["evaluator_id"] for r in rows}),
                          "limitation": "Wilson treats votes as independent; repeated votes by an evaluator are correlated."}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
