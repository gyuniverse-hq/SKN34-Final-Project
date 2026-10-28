"""Spread / sheen / particles from tutorials — never hex, never a video file.

Labels are the only thing a YouTube pass may store. They map onto the AR shader
that is already in components/ar/faceTrackerHtml.ts (blushPow, uLinerGloss, flakeScale).
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

ZONES = ("blush", "eyeliner", "eyeshadow")
TEXTURES = ("matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer")
SPREAD = ("wide", "tight", "unknown")
SHEEN = ("dull", "wet", "unknown")
PARTICLES = ("none", "fine", "chunky", "unknown")

# What the current shader does per zone × 7-way finish. Unknown means the shader
# does not use that axis for that zone.
SHADER_EXPECT: dict[tuple[str, str], dict[str, str]] = {
    ("blush", "matte"): {"spread": "wide", "sheen": "dull", "particles": "none"},
    ("blush", "velvet"): {"spread": "wide", "sheen": "dull", "particles": "none"},
    ("blush", "cream"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("blush", "satin"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("blush", "sheer"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("blush", "glossy"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("blush", "shimmer"): {"spread": "wide", "sheen": "wet", "particles": "fine"},
    ("eyeliner", "matte"): {"spread": "wide", "sheen": "dull", "particles": "none"},
    ("eyeliner", "velvet"): {"spread": "wide", "sheen": "dull", "particles": "none"},
    ("eyeliner", "cream"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("eyeliner", "satin"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("eyeliner", "sheer"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("eyeliner", "glossy"): {"spread": "tight", "sheen": "wet", "particles": "none"},
    ("eyeliner", "shimmer"): {"spread": "tight", "sheen": "wet", "particles": "fine"},
    ("eyeshadow", "matte"): {"spread": "unknown", "sheen": "dull", "particles": "none"},
    ("eyeshadow", "velvet"): {"spread": "unknown", "sheen": "dull", "particles": "none"},
    ("eyeshadow", "cream"): {"spread": "unknown", "sheen": "wet", "particles": "none"},
    ("eyeshadow", "satin"): {"spread": "unknown", "sheen": "wet", "particles": "none"},
    ("eyeshadow", "sheer"): {"spread": "unknown", "sheen": "wet", "particles": "none"},
    ("eyeshadow", "glossy"): {"spread": "unknown", "sheen": "wet", "particles": "none"},
    ("eyeshadow", "shimmer"): {"spread": "unknown", "sheen": "wet", "particles": "chunky"},
}

# Pairs the plan asks to check on device / in tutorials.
CHECK_PAIRS = (
    ("blush", "matte"),
    ("blush", "glossy"),
    ("eyeliner", "matte"),
    ("eyeliner", "glossy"),
    ("eyeshadow", "matte"),
    ("eyeshadow", "shimmer"),
)

QUERIES = {
    ("blush", "matte"): "matte powder blush how to apply tutorial",
    ("blush", "glossy"): "cream blush dewy how to apply tutorial",
    ("eyeliner", "matte"): "matte pencil eyeliner smudge tutorial",
    ("eyeliner", "glossy"): "liquid eyeliner glossy line tutorial",
    ("eyeshadow", "matte"): "matte eyeshadow how to apply tutorial",
    ("eyeshadow", "shimmer"): "glitter shimmer eyeshadow how to apply tutorial",
}


def clean_choice(value: object, allowed: tuple[str, ...]) -> str:
    text = str(value or "unknown").strip().lower()
    return text if text in allowed else "unknown"


def parse_label(raw: dict, zone: str, texture: str) -> dict:
    return {
        "zone": zone if zone in ZONES else "blush",
        "texture": texture if texture in TEXTURES else "matte",
        "spread": clean_choice(raw.get("spread"), SPREAD),
        "sheen": clean_choice(raw.get("sheen"), SHEEN),
        "particles": clean_choice(raw.get("particles"), PARTICLES),
    }


def majority(values: Iterable[str], threshold: float = 0.6) -> str:
    """Keep a label only when non-unknown votes agree at `threshold` (AR_SPEC 6-12)."""
    labeled = [v for v in values if v != "unknown"]
    if len(labeled) < 2:
        return "unknown"
    value, count = Counter(labeled).most_common(1)[0]
    return value if count / len(labeled) >= threshold else "unknown"


def vote_labels(rows: list[dict]) -> dict[tuple[str, str], dict[str, str]]:
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["zone"], row["texture"])
        buckets.setdefault(key, []).append(row)
    out: dict[tuple[str, str], dict[str, str]] = {}
    for key, group in buckets.items():
        out[key] = {
            "spread": majority(r["spread"] for r in group),
            "sheen": majority(r["sheen"] for r in group),
            "particles": majority(r["particles"] for r in group),
        }
    return out


def mismatches(votes: dict[tuple[str, str], dict[str, str]]) -> list[dict]:
    """Axes where a YouTube vote is known and disagrees with the shader."""
    found = []
    for key, got in votes.items():
        expect = SHADER_EXPECT.get(key)
        if not expect:
            continue
        for axis in ("spread", "sheen", "particles"):
            if got[axis] == "unknown" or expect[axis] == "unknown":
                continue
            if got[axis] != expect[axis]:
                found.append(
                    {
                        "zone": key[0],
                        "texture": key[1],
                        "axis": axis,
                        "shader": expect[axis],
                        "vote": got[axis],
                    }
                )
    return found


def tuning_advice(found: list[dict]) -> list[str]:
    """Numeric knobs to touch only when a vote disagrees. Empty = leave TUNING."""
    lines = []
    for row in found:
        z, t, axis, shader, vote = row["zone"], row["texture"], row["axis"], row["shader"], row["vote"]
        if z == "blush" and axis == "spread":
            if shader == "wide" and vote == "tight":
                lines.append("blushPow mix high-rough 0.5 → 0.85 (matte/velvet less powder-spread)")
            elif shader == "tight" and vote == "wide":
                lines.append("blushPow mix low-rough 1.7 → 1.2 (glossy/cream less tight)")
        elif z == "eyeliner" and axis == "sheen":
            if shader == "dull" and vote == "wet":
                lines.append("liner smudge gate uLinerGloss < 0.42 → 0.22 (only very matte blurs)")
            elif shader == "wet" and vote == "dull":
                lines.append("liner smudge gate uLinerGloss < 0.42 → 0.58 (cream/satin also blur)")
        elif z == "eyeshadow" and axis == "particles":
            if shader == "chunky" and vote == "fine":
                lines.append("flakeScaleShimmer 480 → 600 (smaller sparks)")
            elif shader == "chunky" and vote == "none":
                lines.append("keep shimmer flake at 0 until a later vote")
            elif shader == "none" and vote in ("fine", "chunky"):
                lines.append("matte shadow must stay flake 0; ignore particle vote on matte")
        else:
            lines.append(f"{z} {t} {axis}: shader {shader} vs vote {vote} (no TUNING key)")
    return lines
