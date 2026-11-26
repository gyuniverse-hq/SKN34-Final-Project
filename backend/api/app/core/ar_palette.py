"""Shared feature contract for AR batch training and server ranking."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

FEATURE_VERSION = "ar-palette-v1"
FEATURES = (
    "makeup_zone",
    "color_family",
    "lightness",
    "chroma",
    "texture",
    "rating_avg",
    "review_count",
    "prior_activity_count_90d",
    "prior_same_family_share_90d",
    "prior_same_texture_share_90d",
)
CATEGORICAL = ("makeup_zone", "color_family", "texture")
ShadeKey = tuple[str, str]
ColorFamily = Literal["red", "coral", "pink", "berry", "nude", "brown"]


@dataclass(frozen=True)
class Shade:
    family: str
    lightness: float
    chroma: float
    texture: str


def _linear_rgb(hex_value):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_value or ""):
        return None
    rgb = [int(hex_value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb)


def _lab(x, y, z, threshold):
    def f(t):
        return math.cbrt(t) if t > threshold else t / (3 * (6 / 29) ** 2) + 4 / 29

    x, y, z = f(x), f(y), f(z)
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


def _color_family(rgb) -> ColorFamily:
    r, g, b = rgb
    # Keep the classification equivalent to the app's AR filter chips.
    light, a, b_lab = _lab(
        (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047,
        0.2126 * r + 0.7152 * g + 0.0722 * b,
        (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883,
        0.008856,
    )
    chroma = math.hypot(a, b_lab)
    hue = math.degrees(math.atan2(b_lab, a)) % 360
    if chroma < 22 or (chroma < 28 and light >= 55) or (chroma < 32 and light >= 65):
        family = "nude" if light >= 50 else "brown"
    elif 40 <= hue <= 90:
        family = "brown" if light < 40 else "coral"
    elif 25 <= hue < 40:
        family = "brown" if light < 32 and chroma < 45 else "coral" if light >= 62 else "red"
    else:
        family = "berry" if light < 42 else "pink"
    return family


def catalog_color_family(hex_value, measure_method, color_source) -> ColorFamily | None:
    if "placeholder" in (measure_method, color_source):
        return None
    if measure_method not in {"measured", "user_verified"} and (
        measure_method != "estimated"
        or color_source not in {"option_chip", "color_compare", "official_hex"}
    ):
        return None
    rgb = _linear_rgb(hex_value)
    return _color_family(rgb) if rgb is not None else None


def shade_features(hex_value, texture, measure_method, color_source):
    if not texture or "placeholder" in (measure_method, color_source):
        return None
    rgb = _linear_rgb(hex_value)
    if rgb is None:
        return None
    r, g, b = rgb
    light, a, b_lab = _lab(
        (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047,
        0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
        (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883,
        (6 / 29) ** 3,
    )
    return Shade(_color_family(rgb), light, math.hypot(a, b_lab), texture)


def score_inputs(zone, order, catalog, ratings, daily):
    family_counts: dict[str, int] = defaultdict(int)
    texture_counts: dict[str, int] = defaultdict(int)
    weights: dict[ShadeKey, float] = defaultdict(float)
    last_day: dict[ShadeKey, date] = {}
    for key, day, weight in daily:
        weights[key] += weight
        last_day[key] = max(last_day.get(key, day), day)
        if shade := catalog.get(key):
            family_counts[shade.family] += 1
            texture_counts[shade.texture] += 1
    valid_history = sum(family_counts.values())
    preferences = sorted(weights, key=lambda k: (-weights[k], -last_day[k].toordinal(), *k))[:80]
    preferences = [(catalog[k], weights[k]) for k in preferences if k in catalog]
    evidence = sum(weight for _, weight in preferences)
    personal_share = 0.75 * evidence / (evidence + 12)
    average = sum(rating for rating, _ in ratings.values()) / len(ratings) if ratings else 0
    result = []
    for product, shade_id in order:
        key = (product, shade_id)
        shade = catalog.get(key)
        if not shade or product not in ratings:
            continue
        rating, reviews = ratings[product]
        quality = (rating * reviews + 30 * average) / (reviews + 30)
        affinity = sum(
            weight
            * (
                0.4 * (shade.family == prior.family)
                + 0.2 * (shade.texture == prior.texture)
                + 0.2 * max(0, 1 - abs(shade.lightness - prior.lightness) / 35)
                + 0.2 * max(0, 1 - abs(shade.chroma - prior.chroma) / 50)
            )
            for prior, weight in preferences
        ) / (evidence or 1)
        score = (1 - personal_share) * (quality - 1) / 4 + personal_share * affinity
        features = dict(
            zip(
                FEATURES,
                (
                    zone,
                    shade.family,
                    shade.lightness,
                    shade.chroma,
                    shade.texture,
                    rating,
                    reviews,
                    len(daily),
                    family_counts[shade.family] / valid_history if valid_history else None,
                    texture_counts[shade.texture] / valid_history if valid_history else None,
                ),
                strict=True,
            )
        )
        result.append((key, features, score))
    return result, bool(evidence)


def top_chips(rows, scores, personalized):
    remaining = sorted(zip(rows, scores, strict=True), key=lambda row: -row[1])
    selected = []
    families = set()
    while remaining and len(selected) < 3:
        diversify = not personalized or len(selected) == 2
        first = next(
            (row for row, _ in remaining if diversify and row[1]["color_family"] not in families),
            remaining[0][0],
        )
        selected.append(first)
        families.add(first[1]["color_family"])
        remaining = [(row, score) for row, score in remaining if row[0][0] != first[0][0]]
    return selected


def ranked_products(rows, scores, exclude):
    """Highest-scoring shade per product, excluding the products already shown."""
    seen = set(exclude)
    for (key, _, _), _ in sorted(zip(rows, scores, strict=True), key=lambda row: -row[1]):
        product_id, _ = key
        if product_id not in seen:
            seen.add(product_id)
            yield key
