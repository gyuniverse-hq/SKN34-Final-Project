"""Find when the eyeliner and the blush are drawn, and pick a before / after frame pair for each.

Samples the downloaded video once a second, keeps frontal, open-eyed, sharp frames and follows two numbers:
- wing: how much darker the darkest 10% past the outer eye corner is than the chin (eyeliner tail, also mascara and
  a smoky shadow that reaches there),
- cheek: how much redder (Lab a*) the cheek is than the chin (blush).
Step windows, first found wins: gemini.json (gemini_steps.py), then description chapters ("7:49 마스카라 & 아이라이너",
read through the YouTube Data API), then captions.json (captions.py: the densest run of "아이라인" / "블러셔" in the
Korean captions), then the place where the number rises most between the K samples before and after (least reliable:
on i4SZIHG76RI the blush rise landed on the concealer step). Frames are saved at full resolution.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/timeline.py VIDEO_ID [...]
Output: research/data/video_makeup/<id>/timeline.json, frames/*.png (git-ignored)
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from common import (cheek_poly, chin_mask, detect, env_value, hand_landmarker, hand_on_face, lab, landmarker,
                    poly_mask, quality, quality_dict, read_json, tail_poly, video_dir, write_json)

SAMPLE_FPS = 1.0
WORK_WIDTH = 960
K = 5
SEARCH_BEFORE = 40.0
SEARCH_AFTER = 60.0
RISE_REACH = 45.0
ZONES = ("eyeliner", "blush")
# Same chapter pattern and words as backend/api/app/services/description_recipe_service.py.
CHAPTER = re.compile(r"^\s*[\(\[]?(\d{1,2}):(\d{2})(?::(\d{2}))?[\)\]]?\s*[-–:]?\s*(.+?)\s*$", re.M)
CHAPTER_WORDS = {"eyeliner": ("아이라인", "아이라이너"), "blush": ("블러셔", "치크")}


def zone_stats(rgb: np.ndarray, pts: np.ndarray) -> dict:
    shape = rgb.shape[:2]
    oval = pts.astype(np.int32)
    x0, y0 = np.maximum(oval.min(0) - 4, 0)
    x1, y1 = np.minimum(oval.max(0) + 4, [shape[1] - 1, shape[0] - 1])
    sub = lab(rgb[y0:y1, x0:x1])
    local = pts - np.array([x0, y0], dtype=np.float32)
    sub_shape = sub.shape[:2]
    chin = chin_mask(sub_shape, local)
    if chin.sum() < 20:
        return {}
    ref_l, ref_a = float(np.median(sub[..., 0][chin])), float(np.median(sub[..., 1][chin]))
    wing, cheek = [], []
    for k in (0, 1):
        m = poly_mask(sub_shape, tail_poly(local, k))
        if m.sum() >= 20:
            wing.append(ref_l - float(np.percentile(sub[..., 0][m], 10)))
        m = poly_mask(sub_shape, cheek_poly(local, k))
        if m.sum() >= 50:
            cheek.append(float(np.median(sub[..., 1][m])) - ref_a)
    return {"wing": float(np.mean(wing)) if wing else None, "cheek": float(np.mean(cheek)) if cheek else None}


def sample(video: Path) -> tuple[list[dict], float]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(int(round(fps / SAMPLE_FPS)), 1)
    lm = landmarker()
    hl = hand_landmarker()
    rows: list[dict] = []
    for idx in range(total):
        if not cap.grab():
            break
        if idx % step:
            continue
        ok, bgr = cap.retrieve()
        if not ok:
            continue
        scale = WORK_WIDTH / bgr.shape[1]
        rgb = cv2.cvtColor(cv2.resize(bgr, (WORK_WIDTH, int(bgr.shape[0] * scale)), interpolation=cv2.INTER_AREA),
                           cv2.COLOR_BGR2RGB)
        row = {"t": round(idx / fps, 2), "ok": False}
        pts = detect(lm, rgb)
        if pts is not None:
            q = quality(pts, rgb)
            row.update(quality_dict(q))
            if q.ok and hand_on_face(hl, rgb, pts):
                row.update(ok=False, hand=True)
            elif q.ok:
                row.update(zone_stats(rgb, pts))
        rows.append(row)
    cap.release()
    return rows, total / fps


def find_rise(good: list[dict], key: str, k: int = K) -> dict | None:
    """The index where median(next k) - median(previous k) is largest, with that rise and the series noise."""
    vals = [r for r in good if r.get(key) is not None]
    if len(vals) < 2 * k + 1:
        return None
    v = np.array([r[key] for r in vals])
    best_i, best = None, -np.inf
    for i in range(k, len(v) - k + 1):
        rise = float(np.median(v[i:i + k]) - np.median(v[i - k:i]))
        if rise > best:
            best_i, best = i, rise
    noise = float(np.median(np.abs(np.diff(v)))) * 1.4826
    return {"index": best_i, "t": vals[best_i]["t"], "rise": round(best, 2), "noise": round(noise, 2),
            "before": vals[max(best_i - k, 0):best_i], "after": vals[best_i:best_i + 2 * k]}


CANDIDATES = 5  # frames kept per side; measure.py takes the first pair without bangs, captions or a brush over the face


def top(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: -r["score"])[:CANDIDATES]


def earliest(rows: list[dict], span: float = 30.0) -> list[dict]:
    """Best frames within ``span`` seconds of the first one: right after a step, before the next step adds more."""
    return top([r for r in rows if r["t"] <= rows[0]["t"] + span]) if rows else []


def latest(rows: list[dict], span: float = 30.0) -> list[dict]:
    return top([r for r in rows if r["t"] >= rows[-1]["t"] - span]) if rows else []


def chapter_steps(video_id: str) -> dict[str, dict]:
    """Zone → first chapter that names it, ending where the next chapter starts. Description cached locally."""
    cache = video_dir(video_id) / "description.txt"
    if not cache.exists():
        key = env_value("YOUTUBE_API_KEY")
        if not key:
            return {}
        url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
            {"part": "snippet", "id": video_id, "key": key})
        items = json.load(urllib.request.urlopen(url, timeout=30)).get("items", [])
        cache.write_text(items[0]["snippet"]["description"] if items else "", encoding="utf-8")
    chapters = []
    for m in CHAPTER.finditer(cache.read_text(encoding="utf-8")):
        a, b, c, title = m.groups()
        chapters.append((int(a) * 60 + int(b) if c is None else int(a) * 3600 + int(b) * 60 + int(c), title))
    if len(chapters) < 3:
        return {}
    out: dict[str, dict] = {}
    for i, (start, title) in enumerate(chapters):
        for zone, words in CHAPTER_WORDS.items():
            if zone not in out and any(w in title for w in words):
                end = chapters[i + 1][0] if i + 1 < len(chapters) else start + 30
                out[zone] = {"start_seconds": start, "end_seconds": end, "title": title}
    return out


def windows(video_id: str, good: list[dict], duration: float) -> dict:
    gemini = video_dir(video_id) / "gemini.json"
    out: dict = {}
    sources = []
    if gemini.exists():
        sources.append(("gemini", {s["zone"]: s for s in read_json(gemini)["steps"]}))
    sources.append(("chapters", chapter_steps(video_id)))
    captions = video_dir(video_id) / "captions.json"
    if captions.exists():
        sources.append(("captions", read_json(captions)["steps"]))
    rises = {zone: find_rise(good, key) for zone, key in (("eyeliner", "wing"), ("blush", "cheek"))}
    for source, steps in sources:
        for zone in ZONES:
            s = steps.get(zone)
            if zone in out or not s or s.get("start_seconds") is None:
                continue
            start = s["start_seconds"]
            end = s.get("end_seconds") or start + 30
            rise = rises.get(zone)
            # Creators often start a zone before its chapter title; an image rise up to a minute earlier wins.
            begin = rise["t"] if rise and start - 60 <= rise["t"] < start else start
            before: list[dict] = []
            for reach in (SEARCH_BEFORE, 90.0, 150.0):  # a wider reach may include an earlier step (beforeGap says how far)
                before = latest([r for r in good if begin - reach <= r["t"] < begin])
                if before:
                    break
            post = [r for r in good if end < r["t"] <= end + SEARCH_AFTER]
            out[zone] = {"source": source, "t": start, "begin": begin, "end": end,
                         "riseT": rise["t"] if rise else None, "before": before, "after": earliest(post),
                         "beforeGap": round(begin - before[0]["t"], 1) if before else None}
    for zone, rise in rises.items():
        if zone in out or rise is None:
            continue
        # The rise is where the change starts; take the after frames from the end of the after run, once it is drawn,
        # but within RISE_REACH seconds (frontal frames can be minutes apart, and later steps add more).
        pre = [r for r in rise["before"] if r["t"] >= rise["t"] - RISE_REACH]
        post = [r for r in rise["after"] if r["t"] <= rise["t"] + RISE_REACH]
        out[zone] = {"source": "rise", "t": rise["t"], "rise": rise["rise"], "noise": rise["noise"],
                     "significant": bool(rise["rise"] > max(3 * rise["noise"], 2.0)),
                     "before": latest(pre), "after": latest(post, span=15.0)}
    tail = [r for r in good if r["t"] >= 0.8 * duration]
    out["final"] = {"source": "last 20%", "before": least_like_final(good, tail, duration), "after": top(tail)}
    return out


def least_like_final(good: list[dict], tail: list[dict], duration: float, keep: int = 15) -> list[dict]:
    """Bare-face frames for the final pair: in the first half, the frames whose wing and cheek differ most from the
    finished look.

    The first frames are often the finished look shown as an intro (i4SZIHG76RI 0-16 s, BD_3e4xCwi8 9 s), so time
    alone does not find the bare face; the lowest wing value alone picked frames after the liner (lighting moves it).
    """
    have = [r for r in good if r.get("wing") is not None and r.get("cheek") is not None]
    early = [r for r in have if r["t"] < 0.5 * duration]
    done = [r for r in tail if r.get("wing") is not None and r.get("cheek") is not None]
    if not early or not done:
        return []
    fw, fc = float(np.median([r["wing"] for r in done])), float(np.median([r["cheek"] for r in done]))
    sw = float(np.std([r["wing"] for r in have])) or 1.0
    sc = float(np.std([r["cheek"] for r in have])) or 1.0
    far = sorted(early, key=lambda r: -(abs(r["wing"] - fw) / sw + abs(r["cheek"] - fc) / sc))[:keep]
    return top(far)


def save_frame(video: Path, t: float, path: Path) -> bool:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, bgr = cap.read()
    cap.release()
    if ok:
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), bgr)
    return bool(ok)


SAMPLER_VERSION = 3  # bump when sample() changes what a row holds


def run(video_id: str, resample: bool = False) -> dict:
    folder = video_dir(video_id)
    video = folder / "video.mp4"
    if not video.exists():
        raise SystemExit(f"{video_id}: run fetch.py first")
    cached = folder / "timeline.json"
    old = read_json(cached) if cached.exists() and not resample else {}
    if old.get("samplerVersion") == SAMPLER_VERSION:
        rows, duration = old["rows"], old["duration"]
    else:
        rows, duration = sample(video)
    good = [r for r in rows if r.get("ok") and r.get("wing") is not None]
    win = windows(video_id, good, duration)
    for old in (folder / "frames").glob("*.png"):
        old.unlink()
    frames: dict[str, list[float]] = {}
    for zone, w in win.items():
        for side in ("before", "after"):
            for i, r in enumerate(w.get(side) or []):
                if save_frame(video, r["t"], folder / "frames" / f"{zone}_{side}_{i}.png"):
                    frames.setdefault(f"{zone}_{side}", []).append(r["t"])
    summary = {
        "videoId": video_id,
        "samplerVersion": SAMPLER_VERSION,
        "duration": round(duration, 1),
        "samples": len(rows),
        "good": len(good),
        "windows": {z: {k: ([r["t"] for r in v] if isinstance(v, list) else v) for k, v in w.items()}
                    for z, w in win.items()},
        "frames": frames,
    }
    write_json(folder / "timeline.json", {**summary, "rows": rows})
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+")
    ap.add_argument("--resample", action="store_true", help="read the video again even when samples are cached")
    args = ap.parse_args()
    for video_id in args.video_ids:
        s = run(video_id, args.resample)
        print(f"{video_id}: {s['good']}/{s['samples']} good samples, windows {s['windows']}")


if __name__ == "__main__":
    main()
