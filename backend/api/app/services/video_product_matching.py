"""Generate review candidates; no candidate is an approved mapping."""

import re
import unicodedata
from dataclasses import dataclass

from app.schemas.catalog import Product, Shade

RULE_VERSION = "video-match-v1"
EXACT_THRESHOLD = 0.9
CANDIDATE_THRESHOLD = 0.6
PROMO = re.compile(r"기획|단품|증정|더블|세트|올영픽|한정|1\s*\+\s*1", re.I)
BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)")
VOLUME = re.compile(r"\d+(?:\.\d+)?\s*(?:ml|g|ea)\b", re.I)
SHADE_CODE = re.compile(
    r"(?<![a-z0-9])(?:#\s*\d{1,3}|\d{1,3}\s*호|\d{1,3}\s*[a-z])(?![a-z0-9])", re.I
)
NO_OPTION = {"원본에별도옵션없음", "원문에명시정보없음", ""}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower()
    text = VOLUME.sub(" ", PROMO.sub(" ", BRACKETS.sub(" ", text)))
    return "".join(c for c in text if c.isalnum())


def tokens(value: str) -> list[str]:
    text = unicodedata.normalize("NFKC", value).lower()
    text = VOLUME.sub(" ", PROMO.sub(" ", BRACKETS.sub(" ", text)))
    return [word for word in re.findall(r"[^\W_]+", text, flags=re.UNICODE) if len(word) >= 2]


def canonical_brand(value: str, aliases: dict[str, str]) -> str:
    key = normalize(value)
    return normalize(aliases.get(key, key))


def name_score(name: str, product: Product) -> float:
    target = normalize(product.name_ko or product.name)
    query = normalize(name)
    if len(query) < 4 or not target:
        return 0.0
    if query == target or query in target:
        return 1.0
    words = tokens(name)
    return sum(word in target for word in words) / len(words) if words else 0.0


def find_shade(option: str, shades: list[Shade]) -> Shade | None:
    key = normalize(option)
    if key in NO_OPTION:
        return shades[0] if len(shades) == 1 else None
    exact = [shade for shade in shades if normalize(shade.name) == key]
    if len(exact) == 1:
        return exact[0]
    codes = {
        normalize(x) for x in SHADE_CODE.findall(unicodedata.normalize("NFKC", option).lower())
    }
    if not codes:
        return None
    matches = [
        shade
        for shade in shades
        if codes
        & {
            normalize(x)
            for x in SHADE_CODE.findall(unicodedata.normalize("NFKC", shade.name).lower())
        }
    ]
    return matches[0] if len(matches) == 1 else None


def zone_conflict(row: dict, product: Product) -> bool:
    value = f"{row.get('zone', '')} {row.get('category', '')}"
    groups = [
        (("립", "입술"), {"lip"}),
        (("치크", "볼", "블러셔"), {"cheek"}),
        (("눈", "아이", "브로우", "속눈썹", "마스카라"), {"eye"}),
        (("베이스", "얼굴", "윤곽", "파운데이션"), {"base"}),
        (("스킨케어", "피부"), {"skincare", "suncare"}),
    ]
    matches = [allowed for labels, allowed in groups if any(label in value for label in labels)]
    return bool(matches) and product.category not in set.union(*matches)


@dataclass(frozen=True)
class Candidate:
    product: Product
    score: float
    shade: Shade | None


def candidates(row: dict, products: list[Product], aliases: dict[str, str]) -> list[Candidate]:
    brand = canonical_brand(row.get("brand", ""), aliases)
    if not brand:
        return []
    found = []
    for product in products:
        if canonical_brand(product.brand, aliases) != brand:
            continue
        score = name_score(row.get("name", ""), product)
        if score >= CANDIDATE_THRESHOLD:
            found.append(
                Candidate(product, score, find_shade(row.get("option", ""), product.shades))
            )
    return sorted(found, key=lambda c: (-c.score, c.product.id))[:3]


def classify(row: dict, found: list[Candidate]) -> tuple[str, str]:
    if not found:
        return "NO_MATCH", "no_same_brand_candidate"
    top = found[0]
    if (
        "확인 필요" in row.get("reviewStatus", "")
        or zone_conflict(row, top.product)
        or any(
            word in f"{row.get('zone', '')} {row.get('category', '')}"
            for word in ("도구", "스킨케어", "피부")
        )
    ):
        return "REVIEW_REQUIRED", "source_or_zone_requires_review"
    if top.score >= EXACT_THRESHOLD and len(found) == 1:
        if top.shade:
            return "EXACT_MATCH", "product_and_shade_candidate"
        return "VARIANT_MATCH", "product_candidate_shade_unknown"
    return "CANDIDATE_MATCH", "multiple_or_partial_candidates"
