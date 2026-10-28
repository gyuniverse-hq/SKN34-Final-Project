"""YouTube finish labels for blush / liner / shadow (research only).

Does not download videos. Search stores IDs; Gemini reads a public YouTube URL.
Never imported from app/, components/, lib/, or server/. Live AR does not call this.

    python research/finish_labels/youtube_finish.py search
    python research/finish_labels/youtube_finish.py extract
    python research/finish_labels/youtube_finish.py vote
    python research/finish_labels/youtube_finish.py run          # search+extract+vote if keys exist

Keys (repo .env, no EXPO_PUBLIC_): YOUTUBE_API_KEY, GEMINI_API_KEY (or LLM_API_KEY).
Results stay under research/data/finish_labels/ (git-ignored).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from labels import (
    CHECK_PAIRS,
    QUERIES,
    mismatches,
    parse_label,
    tuning_advice,
    vote_labels,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "data" / "finish_labels"
FIXTURE = HERE / "fixtures" / "matching_labels.json"
YT_SEARCH = "https://www.googleapis.com/youtube/v3/search"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
PROMPT = """Watch only how the makeup sits on skin. Ignore product names, people, and color.

Return JSON with keys spread, sheen, particles.
spread: wide (powder edge) or tight (cream patch) or unknown
sheen: dull or wet or unknown
particles: none or fine or chunky or unknown

This clip is about {zone} with a {texture} finish. If the clip is not that, use unknown.
Do not output hex codes or names."""


def load_env_key(*names: str) -> str:
    for name in names:
        got = os.environ.get(name, "").strip()
        if got:
            return got
    env = ROOT / ".env"
    if not env.is_file():
        return ""
    wanted = {n: "" for n in names}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("EXPO_PUBLIC_"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k in wanted:
            wanted[k] = v.strip().strip('"').strip("'")
    for name in names:
        if wanted[name]:
            return wanted[name]
    return ""


def dump(name: str, payload: object) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def search(max_results: int = 3) -> list[dict]:
    key = load_env_key("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("YOUTUBE_API_KEY missing")
    rows: list[dict] = []
    for zone, texture in CHECK_PAIRS:
        query = QUERIES[(zone, texture)]
        params = urllib.parse.urlencode(
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": max_results,
                "safeSearch": "strict",
                "videoEmbeddable": "true",
                "key": key,
            }
        )
        req = urllib.request.Request(
            f"{YT_SEARCH}?{params}",
            headers={"User-Agent": "SKN34-finish-labels/0.1"},
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            body = json.loads(res.read().decode("utf-8"))
        for item in body.get("items") or []:
            video_id = (item.get("id") or {}).get("videoId")
            if not video_id:
                continue
            rows.append(
                {
                    "videoId": video_id,
                    "zone": zone,
                    "texture": texture,
                    "query": query,
                }
            )
    dump("videos.json", rows)
    return rows


def extract_one(video_id: str, zone: str, texture: str) -> dict:
    key = load_env_key("GEMINI_API_KEY", "LLM_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY or LLM_API_KEY missing")
    model = load_env_key("GEMINI_MODEL") or "gemini-2.0-flash"
    url = f"{GEMINI_URL.format(model=model)}?key={urllib.parse.quote(key)}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT.format(zone=zone, texture=texture)},
                    {"file_data": {"file_uri": f"https://www.youtube.com/watch?v={video_id}"}},
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "SKN34-finish-labels/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            body = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Gemini HTTP {exc.code}: {detail[:400]}") from exc
    parts = (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text = "".join(p.get("text") or "" for p in parts).strip()
    try:
        raw = json.loads(text) if text else {}
    except json.JSONDecodeError:
        raw = {}
    label = parse_label(raw if isinstance(raw, dict) else {}, zone, texture)
    label["videoId"] = video_id
    return label


def extract(videos: list[dict] | None = None) -> list[dict]:
    if videos is None:
        path = OUT / "videos.json"
        if not path.is_file():
            raise SystemExit("run search first")
        videos = json.loads(path.read_text(encoding="utf-8"))
    labels = [extract_one(v["videoId"], v["zone"], v["texture"]) for v in videos]
    dump("labels.json", labels)
    return labels


def vote(rows: list[dict] | None = None, source: Path | None = None) -> dict:
    if rows is None:
        path = source or (OUT / "labels.json" if (OUT / "labels.json").is_file() else FIXTURE)
        if not path.is_file():
            raise SystemExit("run extract first")
        rows = json.loads(path.read_text(encoding="utf-8"))
    votes = vote_labels(rows)
    found = mismatches(votes)
    advice = tuning_advice(found)
    report = {
        "votes": {f"{z}:{t}": v for (z, t), v in votes.items()},
        "mismatches": found,
        "tuningAdvice": advice,
        "changeTuning": bool(advice),
    }
    dump("vote.json", report)
    return report


def main(argv: list[str]) -> int:
    cmd = (argv[1] if len(argv) > 1 else "vote").strip()
    if cmd == "search":
        rows = search()
        print(f"{len(rows)} video ids → {OUT / 'videos.json'}")
        return 0
    if cmd == "extract":
        labels = extract()
        print(f"{len(labels)} labels → {OUT / 'labels.json'}")
        return 0
    if cmd == "vote":
        source = FIXTURE if "--fixture" in argv else None
        report = vote(source=source)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if cmd == "run":
        videos = search()
        labels = extract(videos)
        report = vote(labels)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    raise SystemExit("usage: youtube_finish.py search|extract|vote|run")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
