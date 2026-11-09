"""Collect measure.json and captions.json of every video into numbers-only files and print a table.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/summary.py [--out FILE]
Output (committable, no images): research/video_makeup/results/<date>.json (shapes) and <date>_products.json
(when each listed product is named in the captions, with shade words) by default.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from common import DATA, STYLE_LOOKS, read_json, write_json


REVIEW = Path(__file__).parent / "results" / "review.json"


def review_for(reviews: dict, video_id: str, name: str, pair: dict) -> str:
    """ok / bad from review.json, only while the reviewed frames are still the measured ones."""
    r = reviews.get(video_id, {}).get(name)
    if not r or r.get("frames") != [pair.get("before"), pair.get("after")]:
        return "-"
    return f"{r['check']} ({r['by']})"


def row(video_id: str, title: str, name: str, pair: dict, reviews: dict) -> dict:
    liner = pair.get("eyeliner", {})
    blush = pair.get("blush", {})
    return {
        "review": review_for(reviews, video_id, name, pair),
        "videoId": video_id,
        "title": title,
        "pair": name,
        "source": (pair.get("window") or {}).get("source"),
        "before": pair.get("before"),
        "after": pair.get("after"),
        "occlusion": pair.get("occlusion"),
        "eyesDiffer": pair.get("eyesDiffer"),
        "usable": bool(pair.get("ok")) and not pair.get("rejected")
        and bool(liner.get("geometry") or blush.get("geometry")),
        "eyeliner": liner.get("geometry"),
        "nearestChip": liner.get("nearestChip"),
        "eyeGap": liner.get("eyeGap"),
        "shadowHeight": liner.get("shadowHeight"),
        "blush": blush.get("geometry"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / f"{date.today():%Y%m%d}.json")
    args = ap.parse_args()
    titles = {x["id"]: x["title"] for x in read_json(STYLE_LOOKS)}
    reviews = read_json(REVIEW) if REVIEW.exists() else {}
    rows = []
    for path in sorted(DATA.glob("*/measure.json")):
        m = read_json(path)
        for name, pair in m["pairs"].items():
            rows.append(row(m["videoId"], titles.get(m["videoId"], ""), name, pair, reviews))
    write_json(args.out, rows)
    products = []
    for path in sorted(DATA.glob("*/captions.json")):
        c = read_json(path)
        for r in c["listed"]:
            m = r["match"]
            products.append({"videoId": c["videoId"], "captions": c["source"], "number": r["number"], "brand": r["brand"],
                             "name": r["name"], "listedOption": r["listedOption"],
                             "seconds": m["seconds"] if m else None, "said": m["text"] if m else None,
                             "shadeCandidates": m["shadeCandidates"] if m else []})
    product_out = args.out.with_name(args.out.stem + "_products.json")
    write_json(product_out, products)
    named = [p for p in products if p["seconds"] is not None]
    filled = [p for p in named if p["shadeCandidates"] and "원문에 명시" in (p["listedOption"] or "")]
    print(f"captions: {len(products)} listed products, {len(named)} named with a time, "
          f"{len(filled)} with a shade candidate where the list has none → {product_out}")
    print("| 영상 | 제목 | 쌍 | 구간 | 전→후(초) | 가림 | 자동 | 검토 | 아이라인 (길이·각도·두께·아래) | 칩 | 블러셔 (위치·크기·번짐) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        g, b = r["eyeliner"], r["blush"]
        liner = f"{g['length']:.2f} · {g['angle']:.0f}° · {g['thickness']:.2f} · {'O' if g['linerLower'] else '-'}" if g else "-"
        blush = f"{b['blushPlacement']} · {b['blushSize']:.2f} · {b['blushSoftness']:.2f}" if b else "-"
        print(f"| {r['videoId']} | {r['title']} | {r['pair']} | {r['source'] or '-'} | {r['before']}→{r['after']} | "
              f"{r['occlusion']} | {'O' if r['usable'] else 'X'} | {r['review']} | {liner} | {r['nearestChip'] or '-'} | {blush} |")
    ok = [r for r in rows if r["review"].startswith("ok")]
    print(f"\n{len(rows)} pairs, {sum(r['usable'] for r in rows)} pass the automatic checks, {len(ok)} reviewed ok → {args.out}")


if __name__ == "__main__":
    main()
