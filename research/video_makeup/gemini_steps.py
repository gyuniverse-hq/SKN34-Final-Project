"""When each zone is drawn and which product is used at that moment, read by Gemini from the public video.

Gemini watches the YouTube URL RUNS times (nothing is uploaded); a zone or product is kept only when most runs agree.
The products are then linked to the video's list in backend/api/app/catalog_data/style_looks.json, so a missing
shade can be filled after review (nothing is written back automatically).

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/gemini_steps.py VIDEO_ID [...] [--runs 3]
Needs GEMINI_API_KEY in .env. Output: research/data/video_makeup/<id>/gemini.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter

from common import STYLE_LOOKS, env_value, read_json, video_dir, write_json

ZONES = ("foundation", "brow", "eyeshadow", "eyeliner", "mascara", "blush", "contour", "highlighter", "lip")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.6-flash"  # backend/api/app/core/config.py

PROMPT = (
    "This is a Korean makeup tutorial video. List the makeup steps in the order they are applied. For each step "
    "give zone (allowed values only), start_seconds (the first second the product touches the face for that zone) "
    "and end_seconds (the last second of that zone's application). For each step also list the products used: "
    "brand and name as written on screen, in the description or said aloud (keep the original Korean), shade "
    "(the number or color name, only if shown or said), seconds (when the product is first shown or named) and "
    "quote (the short words said or captioned about it, original language). Leave out anything you cannot see or "
    "hear. Never guess a shade. Do not describe the person."
)
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "steps": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "zone": {"type": "STRING", "enum": list(ZONES)},
                    "start_seconds": {"type": "INTEGER"},
                    "end_seconds": {"type": "INTEGER"},
                    "products": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "brand": {"type": "STRING"},
                                "name": {"type": "STRING"},
                                "shade": {"type": "STRING"},
                                "seconds": {"type": "INTEGER"},
                                "quote": {"type": "STRING"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["zone", "start_seconds"],
            },
        }
    },
    "required": ["steps"],
}


def ask(video_id: str, key: str, model: str) -> dict:
    body = {
        "contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={video_id}"}},
                                {"text": PROMPT}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.2},
    }
    req = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for delay in (10, 30, 60, None):
        try:
            with urllib.request.urlopen(req, timeout=600) as res:
                payload = json.load(res)
            return json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or delay is None:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")


def norm(text: str | None) -> str:
    return re.sub(r"[\s\-_·,./()\[\]]+", "", (text or "").lower())


def vote(runs: list[dict]) -> list[dict]:
    """A zone (and a product within it) needs a majority of runs; times are medians, shades the most common."""
    need = len(runs) // 2 + 1
    per_zone: dict[str, list[dict]] = {}
    for run in runs:
        seen: set[str] = set()
        for step in run.get("steps", []):
            if step.get("zone") in ZONES and step["zone"] not in seen:
                seen.add(step["zone"])
                per_zone.setdefault(step["zone"], []).append(step)
    steps = []
    for zone, items in per_zone.items():
        if len(items) < need:
            continue
        starts = [s["start_seconds"] for s in items if s.get("start_seconds") is not None]
        ends = [s["end_seconds"] for s in items if s.get("end_seconds") is not None]
        groups: dict[str, list[dict]] = {}
        for s in items:
            for p in {norm(p.get("brand")) + norm(p.get("name")): p for p in s.get("products", [])}.values():
                groups.setdefault(norm(p.get("brand")) + norm(p.get("name")), []).append(p)
        products = []
        for group in groups.values():
            if len(group) < need:
                continue
            shades = Counter(p["shade"] for p in group if p.get("shade"))
            shade, count = shades.most_common(1)[0] if shades else (None, 0)
            secs = [p["seconds"] for p in group if p.get("seconds") is not None]
            products.append({
                "brand": group[0].get("brand"),
                "name": group[0].get("name"),
                "shade": shade if count >= need else None,
                "seconds": round(statistics.median(secs)) if secs else None,
                "quote": group[0].get("quote"),
                "votes": len(group),
            })
        steps.append({
            "zone": zone,
            "start_seconds": round(statistics.median(starts)) if starts else None,
            "end_seconds": round(statistics.median(ends)) if ends else None,
            "products": sorted(products, key=lambda p: p["seconds"] if p["seconds"] is not None else 10**9),
            "votes": len(items),
            "runs": len(runs),
        })
    return sorted(steps, key=lambda s: s["start_seconds"] if s["start_seconds"] is not None else 10**9)


def bigrams(text: str) -> set[str]:
    t = norm(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def link_listed(video_id: str, steps: list[dict]) -> list[dict]:
    """Pair each listed product with the best spoken/shown mention (character-bigram overlap ≥ 0.5)."""
    look = next((x for x in read_json(STYLE_LOOKS) if x["id"] == video_id), None)
    if look is None:
        return []
    mentions = [(s["zone"], p) for s in steps for p in s["products"]]
    out = []
    for item in look["products"]:
        listed = bigrams(f"{item.get('brand', '')}{item.get('name', '')}")
        best, best_score = None, 0.0
        for zone, p in mentions:
            seen = bigrams(f"{p.get('brand') or ''}{p.get('name') or ''}")
            score = len(listed & seen) / max(len(listed), 1)
            if score > best_score:
                best, best_score = (zone, p), score
        row = {"number": item["number"], "brand": item.get("brand"), "name": item.get("name"),
               "listedOption": item.get("option"), "match": None}
        if best and best_score >= 0.5:
            zone, p = best
            row["match"] = {"zone": zone, "seconds": p["seconds"], "shade": p["shade"], "quote": p["quote"],
                            "score": round(best_score, 2)}
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    key = env_value("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (.env)")
    model = env_value("GEMINI_MODEL") or DEFAULT_MODEL
    for video_id in args.video_ids:
        runs = []
        for i in range(args.runs):
            try:
                runs.append(ask(video_id, key, model))
            except (urllib.error.URLError, KeyError, ValueError) as exc:
                print(f"{video_id}: run {i + 1} failed ({exc})")
        if not runs:
            continue
        steps = vote(runs)
        listed = link_listed(video_id, steps)
        write_json(video_dir(video_id) / "gemini.json",
                   {"videoId": video_id, "model": model, "runs": len(runs), "steps": steps, "listed": listed,
                    "raw": runs})
        filled = sum(1 for r in listed if r["match"] and r["match"]["shade"])
        print(f"{video_id}: steps {[s['zone'] for s in steps]}, listed {len(listed)}, "
              f"linked {sum(1 for r in listed if r['match'])}, shade found {filled}")


if __name__ == "__main__":
    main()
