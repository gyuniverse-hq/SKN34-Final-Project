"""When each zone is talked about and when each listed product is named, from the video's Korean captions (no Gemini).

Downloads the creator's Korean caption track when there is one, else YouTube's automatic Korean captions (json3, with
times). Then:
- steps: for eyeliner and blush, the densest STEP_SPAN-second run of mentions ("아이라인", "블러셔" ...) gives the
  start (first mention of the run) and the end (last mention + STEP_TAIL). One-off mentions in an intro lose to the
  run where the creator is actually applying it.
- listed: each product of the video in backend/api/app/catalog_data/style_looks.json is paired with the first caption
  that names it (brand + name, character-bigram overlap), with any shade-looking words in it ("21호", "03번", "21N").
  These are candidates for the empty option column, for review; nothing is written back.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/captions.py VIDEO_ID [...]
Output: research/data/video_makeup/<id>/captions.json (git-ignored); timeline.py reads its steps.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yt_dlp

from common import STYLE_LOOKS, read_json, video_dir, write_json

STEP_WORDS = {
    "eyeliner": ("아이라인", "아이라이너", "라이너"),
    "blush": ("블러셔", "블러쉬", "블러시", "치크"),
}
NOT_STEP = {"eyeliner": ("립라이너", "립 라이너", "애교살 라이너", "브로우 라이너")}
STEP_SPAN = 90.0
STEP_TAIL = 20.0
SHADE = re.compile(r"(\d{1,3}\s?(?:호|번)|\b\d{2}\s?(?:NC|NW|N|W|C)\b|#\s?\d{1,3})")
MATCH_MIN = 0.6


def pick_track(info: dict) -> tuple[str, str] | None:
    """The creator's Korean track ("ko" or "ko-<id>"), else automatic "ko". Never a machine translation ("ko-en-...")."""
    manual = sorted(k for k in (info.get("subtitles") or {}) if k == "ko" or re.fullmatch(r"ko-[A-Za-z0-9_]{6,}", k))
    if manual:
        return manual[0], "manual"
    if "ko" in (info.get("automatic_captions") or {}):
        return "ko", "auto"
    return None


def fetch(video_id: str) -> tuple[list[dict], str]:
    """Caption cues [{t, end, text}] and which track they came from; cached as captions.<kind>.json3."""
    folder = video_dir(video_id)
    for kind in ("manual", "auto"):
        cached = folder / f"captions.{kind}.json3"
        if cached.exists():
            return parse_json3(cached.read_text(encoding="utf-8")), kind
    base = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True}
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(base) as ydl:
        track = pick_track(ydl.extract_info(url, download=False))
    if track is None:
        return [], "none"
    lang, kind = track
    opts = {**base, "subtitlesformat": "json3", "subtitleslangs": [re.escape(lang)],
            "writesubtitles" if kind == "manual" else "writeautomaticsub": True, "outtmpl": str(folder / "dl")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    got = folder / f"dl.{lang}.json3"
    if not got.exists():
        return [], "none"
    cached = folder / f"captions.{kind}.json3"
    got.replace(cached)
    return parse_json3(cached.read_text(encoding="utf-8")), kind


def parse_json3(text: str) -> list[dict]:
    cues = []
    for e in json.loads(text).get("events", []):
        words = "".join(s.get("utf8", "") for s in e.get("segs") or []).replace("\n", " ").strip()
        if not words or words.startswith("["):
            continue
        start = e.get("tStartMs", 0) / 1000
        cues.append({"t": round(start, 2), "end": round(start + e.get("dDurationMs", 0) / 1000, 2), "text": words})
    return cues


def mentions(cues: list[dict], zone: str) -> list[float]:
    out = []
    for c in cues:
        text = c["text"]
        for bad in NOT_STEP.get(zone, ()):
            text = text.replace(bad, "")
        if any(w in text for w in STEP_WORDS[zone]):
            out.append(c["t"])
    return out


def caption_steps(cues: list[dict]) -> dict[str, dict]:
    steps = {}
    for zone in STEP_WORDS:
        times = mentions(cues, zone)
        if not times:
            continue
        best_run: list[float] = []
        for i, t in enumerate(times):
            run = [x for x in times[i:] if x <= t + STEP_SPAN]
            if len(run) > len(best_run):
                best_run = run
        steps[zone] = {"start_seconds": round(best_run[0]), "end_seconds": round(best_run[-1] + STEP_TAIL),
                       "mentions": len(best_run), "allMentions": len(times)}
    return steps


def norm(text: str | None) -> str:
    return re.sub(r"[\s\-_·,./()\[\]!?~'\"]+", "", (text or "").lower())


def bigrams(text: str) -> set[str]:
    t = norm(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


# Spoken brand names the automatic captions write differently (backend/api/seed/source/brand_aliases.csv is empty).
BRAND_ALIASES = {
    "3CE": ("쓰리씨이", "쓰리씨"),
    "롬앤": ("롬엔", "romand"),
    "삐아": ("bbia",),
    "클리오": ("clio",),
    "에뛰드": ("etude",),
    "페리페라": ("peripera",),
    "메이블린뉴욕": ("메이블린",),
    "투쿨포스쿨": ("투쿨",),
    "데이지크": ("dasique",),
    "어뮤즈": ("amuse",),
}
GENERIC = {"립", "아이", "컬러", "블랙", "브라운", "핑크", "스킨", "베이스", "커버"}
UNKNOWN_BRAND = {"", "확인 필요"}
# Product kinds: every concealer step says "컨실러", so a kind counts only next to the brand.
KINDS = {"컨실러", "쉐딩", "블러셔", "틴트", "마스카라", "하이라이터", "아이라이너", "펜슬", "팔레트", "아이팔레트", "립스틱",
         "프렙", "쿠션", "파운데이션", "섀도우", "섀도", "글로스", "프라이머", "파우더", "스틱", "브로우"}


def brand_said(brand: str, text: str) -> bool:
    t = norm(text)
    return any(norm(b) and norm(b) in t for b in (brand, *BRAND_ALIASES.get(brand, ())))


def name_words(name: str) -> list[str]:
    """Name words worth finding on their own: 2+ characters, not a bare number or a word every product has."""
    return [w for w in (norm(x) for x in name.split()) if len(w) >= 2 and not w.isdigit() and w not in GENERIC]


class Speech:
    """Is a name word just common speech in this video? Counted the way names are found: inside space-free cues."""

    def __init__(self, cues: list[dict]) -> None:
        self._cues = [norm(c["text"]) for c in cues]
        self._need = max(3, int(0.02 * len(cues)))
        self._seen: dict[str, bool] = {}

    def __contains__(self, word: str) -> bool:
        if word not in self._seen:
            self._seen[word] = sum(word in c for c in self._cues) >= self._need
        return self._seen[word]


def names_product(item: dict, text: str, frequent=frozenset()) -> tuple[bool, list[str]]:
    """Captions name a product by brand + part of the name ("클리오 립펜슬"), not the catalogue title.

    Brand said + any name word, or two name words of which one is specific (not a product kind and not common in
    this video's speech), or most of the full name.
    """
    t = norm(text)
    hits = [w for w in name_words(item.get("name", "")) if w in t]
    specific = [w for w in hits if w not in frequent
                and not any(w == k or w.endswith(k) and len(w) <= len(k) + 1 for k in KINDS)]
    full = len(bigrams(item.get("name", "")) & bigrams(text)) / max(len(bigrams(item.get("name", ""))), 1)
    if item.get("brand", "") in UNKNOWN_BRAND:
        # Rows without a brand are often description sentences parsed as products ("컬러감도 데일리 스러워서 ...").
        return len(specific) >= 2 or full >= MATCH_MIN, hits
    said = brand_said(item.get("brand", ""), text)
    return (said and bool(hits)) or (len(hits) >= 2 and bool(specific)) or full >= MATCH_MIN, hits


def anchor(item: dict, cues: list[dict], i: int, hits: list[str]) -> int:
    """The cue in the window that says the brand (else the first name word): its time and shade words are the match."""
    for j in range(i, min(i + 3, len(cues))):
        if brand_said(item.get("brand", ""), cues[j]["text"]):
            return j
    for j in range(i, min(i + 3, len(cues))):
        if any(w in norm(cues[j]["text"]) for w in hits):
            return j
    return i


def link_listed(video_id: str, cues: list[dict]) -> list[dict]:
    """First caption window (this cue and the next two; names break across lines) that names each listed product."""
    look = next((x for x in read_json(STYLE_LOOKS) if x["id"] == video_id), None)
    if look is None:
        return []
    frequent = Speech(cues)
    out = []
    for item in look["products"]:
        row = {"number": item["number"], "brand": item.get("brand"), "name": item.get("name"),
               "listedOption": item.get("option"), "match": None}
        for i in range(len(cues)):
            ok, hits = names_product(item, " ".join(x["text"] for x in cues[i:i + 3]), frequent)
            if not ok:
                continue
            j = anchor(item, cues, i, hits)
            said = " ".join(x["text"] for x in cues[j:j + 2])
            ok, hits = names_product(item, said, frequent)  # brand and name words must meet within two lines
            if not ok:
                continue
            row["match"] = {"seconds": cues[j]["t"], "text": said, "words": hits,
                            "shadeCandidates": sorted({m.replace(" ", "") for m in SHADE.findall(said)})}
            break
        out.append(row)
    return out


def run(video_id: str) -> dict:
    cues, source = fetch(video_id)
    result = {"videoId": video_id, "source": source, "cues": len(cues), "steps": caption_steps(cues),
              "listed": link_listed(video_id, cues)}
    write_json(video_dir(video_id) / "captions.json", {**result, "cueList": cues})
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+")
    args = ap.parse_args()
    for video_id in args.video_ids:
        try:
            r = run(video_id)
        except yt_dlp.utils.DownloadError as exc:
            print(f"{video_id}: captions failed ({exc})")
            continue
        linked = [x for x in r["listed"] if x["match"]]
        shades = [x for x in linked if x["match"]["shadeCandidates"]]
        print(f"{video_id}: {r['source']} {r['cues']} cues, steps {r['steps']}, listed {len(r['listed'])}, "
              f"named {len(linked)}, with shade words {len(shades)}")


if __name__ == "__main__":
    main()
