"""Collect and apply missing YouTube product assets from four retail sources.

Run from backend/api. Collection is resumable and writes a review CSV. The
preflight phase checks it; apply updates raw YouTube fields, never serving rows.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import difflib
import getpass
import json
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode

import asyncpg
import httpx
import requests
from enrich_glowpick import (
    DetailParser,
    GlowpickClient,
    RateLimitStopped,
    _parse_detail,
)

ROOT = Path(__file__).resolve().parent
EXCLUSIONS = ROOT / "non_product_exclusions.csv"
REVIEWED_PRODUCT_URLS = ROOT / "reviewed_product_urls.csv"
REVIEWED_HWAHAE_URLS = ROOT / "reviewed_hwahae_urls.csv"
REVIEWED_PRODUCT_OPTIONS = ROOT / "reviewed_product_options.csv"
REVIEWED_CANDIDATE_OVERRIDES = ROOT / "reviewed_candidate_overrides.csv"
REVIEWED_PRICE_OVERRIDES = ROOT / "reviewed_price_overrides.csv"
REVIEWED_IDENTITY_OVERRIDES = ROOT / "reviewed_identity_overrides_v316.csv"
REVIEWED_NOT_FOUND = ROOT / "reviewed_not_found_products_v317.csv"
DEFAULT_REPORT = Path.home() / "Downloads" / "youtube-catalog-enrichment-v317.csv"
FIELDS = (
    "yt_product_id",
    "source_brand",
    "source_product_name",
    "source_option_name",
    "source_category",
    "is_tool",
    "tags",
    "lookup_status",
    "selected_site",
    "selected_brand",
    "selected_product_name",
    "selected_product_url",
    "match_basis",
    "price_krw",
    "price_source",
    "volume",
    "volume_source",
    "image_url",
    "image_source",
    "review_reason",
    "error",
)
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
WAIT_SECONDS = (60, 180, 600)
HTTP_5XX_RETRY_SECONDS = (5, 15, 30)
SCRIPT_VERSION = "3.18"
# Verified brand spellings that may appear at the start of a source product
# title even when the source brand column is marked as unknown.
BRAND_SPELLING_EQUIVALENTS = (
    {"urang", "유랑"},
    {"aperire", "아페리레"},
    {"chica-y-chico", "치카이치코"},
    {"mac", "맥"},
    {"revecen", "레브쌍"},
    {"naming", "네이밍"},
    {"프로에잇청담", "프로에잇"},
    # Source titles sometimes use "에이지 투에니스" for AGE20'S, while
    # candidate catalogs use the official spelling "에이지투웨니스".
    {"에이지투에니스", "에이지투웨니스", "age20s"},
)
# These source rows were manually checked against the v34 report. The selected
# Hwahae item is a different lash model and must not remain as a match candidate.
REJECTED_CANDIDATE_URLS_BY_SOURCE = {
    "yt-1c26bf4a102fad3252b4": "https://www.hwahae.co.kr/products/2158604",
}
def clean(value: str | None) -> str:
    return " ".join((value or "").split())


def key(value: str | None) -> str:
    return "".join(char.casefold() for char in clean(value) if char.isalnum())


GENERIC_PRODUCT_TERMS = tuple(
    key(term)
    for term in (
        "쿠션", "앰플", "세럼", "에센스", "토너", "크림", "로션", "선크림",
        "선스틱", "파운데이션", "컨실러", "프라이머", "파우더", "팩트",
        "블러셔", "치크", "틴트", "립스틱", "립글로스", "립밤", "립펜슬",
        "아이섀도", "섀도우", "팔레트", "아이라이너", "마스카라", "브로우",
        "아이브로우", "브러시", "브러쉬", "퍼프", "뷰러", "속눈썹",
    )
)


def load_brand_aliases() -> tuple[dict[str, str], dict[str, str]]:
    with (ROOT / "brand_aliases_reviewed.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    aliases = {key(row["yt_brand"]): key(row["oy_brand"]) for row in rows}
    search_names: dict[str, str] = {}
    for row in rows:
        search_names[key(row["yt_brand"])] = row["oy_brand"].strip()
        search_names[key(row["oy_brand"])] = row["oy_brand"].strip()
    return aliases, search_names


BRAND_ALIASES, BRAND_SEARCH_NAMES = load_brand_aliases()


def reviewed_product_ids() -> dict[str, int]:
    with REVIEWED_PRODUCT_URLS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    product_ids = {row["yt_product_id"]: int(row["glowpick_product_id"]) for row in rows}
    if len(product_ids) != len(rows) or any(product_id <= 0 for product_id in product_ids.values()):
        raise ValueError(f"Invalid reviewed product URLs: {REVIEWED_PRODUCT_URLS}")
    return product_ids


REVIEWED_PRODUCT_IDS = reviewed_product_ids()


def reviewed_hwahae_ids() -> dict[str, tuple[int, str]]:
    if not REVIEWED_HWAHAE_URLS.exists():
        return {}
    with REVIEWED_HWAHAE_URLS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if rows and set(rows[0]) != {"yt_product_id", "hwahae_product_id", "search_query"}:
        raise ValueError(f"Unexpected reviewed Hwahae columns: {REVIEWED_HWAHAE_URLS}")
    result: dict[str, tuple[int, str]] = {}
    for row in rows:
        source_id = clean(row["yt_product_id"])
        product_id = int(row["hwahae_product_id"])
        query = clean(row["search_query"])
        if not source_id or source_id in result or product_id <= 0 or not query:
            raise ValueError(f"Invalid reviewed Hwahae URL: {source_id}")
        result[source_id] = (product_id, query)
    return result


REVIEWED_HWAHAE_IDS = reviewed_hwahae_ids()


def reviewed_product_options() -> dict[str, str]:
    if not REVIEWED_PRODUCT_OPTIONS.exists():
        return {}
    with REVIEWED_PRODUCT_OPTIONS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    options = {row["yt_product_id"]: clean(row["option_name"]) for row in rows}
    if len(options) != len(rows) or any(not value for value in options.values()):
        raise ValueError(f"Invalid reviewed product options: {REVIEWED_PRODUCT_OPTIONS}")
    return options


REVIEWED_PRODUCT_OPTIONS_BY_ID = reviewed_product_options()


def reviewed_candidate_overrides() -> dict[str, dict[str, str]]:
    with REVIEWED_CANDIDATE_OVERRIDES.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "yt_product_id",
        "selected_site",
        "selected_brand",
        "selected_product_name",
        "selected_product_url",
        "price_krw",
        "price_source",
        "volume",
        "volume_source",
        "image_url",
        "image_source",
    }
    if rows and set(rows[0]) != required:
        raise ValueError(f"Unexpected reviewed candidate columns: {REVIEWED_CANDIDATE_OVERRIDES}")
    overrides: dict[str, dict[str, str]] = {}
    for row in rows:
        product_id = clean(row.get("yt_product_id"))
        url = clean(row.get("selected_product_url"))
        if (
            not product_id
            or product_id in overrides
            or row.get("selected_site") not in {"glowpick", "hwahae", "powderroom", "oliveyoung", "brand_official"}
            or not url.startswith("https://")
            or not clean(row.get("selected_product_name"))
            or any(
                value
                and not value.startswith("https://")
                and value != "raw_yt_product"
                for value in (row.get("price_source"), row.get("volume_source"), row.get("image_source"))
            )
        ):
            raise ValueError(f"Invalid reviewed candidate override: {product_id}")
        if row.get("price_krw") and int(row["price_krw"]) <= 0:
            raise ValueError(f"Invalid reviewed candidate price: {product_id}")
        if row.get("image_url") and not row["image_url"].startswith("https://"):
            raise ValueError(f"Invalid reviewed candidate image: {product_id}")
        overrides[product_id] = row
    return overrides


REVIEWED_CANDIDATE_OVERRIDES_BY_ID = reviewed_candidate_overrides()


def reviewed_identity_overrides() -> dict[str, dict[str, str]]:
    with REVIEWED_IDENTITY_OVERRIDES.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {"yt_product_id", "selected_product_url", "approval_reason"}
    if rows and set(rows[0]) != expected:
        raise ValueError(f"Unexpected reviewed identity columns: {REVIEWED_IDENTITY_OVERRIDES}")
    result = {clean(row["yt_product_id"]): row for row in rows}
    if len(result) != len(rows) or any(
        not source.startswith("yt-")
        or not clean(row.get("selected_product_url", "")).startswith("https://")
        or not clean(row.get("approval_reason"))
        for source, row in result.items()
    ):
        raise ValueError(f"Invalid reviewed identity overrides: {REVIEWED_IDENTITY_OVERRIDES}")
    return result


REVIEWED_IDENTITY_OVERRIDES_BY_ID = reviewed_identity_overrides()


def reviewed_not_found_products() -> dict[str, str]:
    if not REVIEWED_NOT_FOUND.exists():
        return {}
    with REVIEWED_NOT_FOUND.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {"yt_product_id", "review_reason"}
    if rows and set(rows[0]) != expected:
        raise ValueError(f"Unexpected reviewed not-found columns: {REVIEWED_NOT_FOUND}")
    result = {clean(row["yt_product_id"]): clean(row["review_reason"]) for row in rows}
    if len(result) != len(rows) or any(
        not product_id.startswith("yt-") or not reason
        for product_id, reason in result.items()
    ):
        raise ValueError(f"Invalid reviewed not-found decisions: {REVIEWED_NOT_FOUND}")
    return result


REVIEWED_NOT_FOUND_BY_ID = reviewed_not_found_products()


def reviewed_identity_matches(row: dict, candidate: dict) -> bool:
    approved = REVIEWED_IDENTITY_OVERRIDES_BY_ID.get(row.get("yt_product_id"))
    candidate_url = clean(candidate.get("url"))
    if not candidate_url and candidate.get("product_id"):
        candidate_url = f"https://www.glowpick.com/products/{candidate['product_id']}"
    return bool(
        approved
        and candidate_url
        and candidate_url == clean(approved.get("selected_product_url"))
    )


def reviewed_price_overrides() -> dict[str, tuple[int, str]]:
    with REVIEWED_PRICE_OVERRIDES.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    overrides: dict[str, tuple[int, str]] = {}
    for row in rows:
        product_id = clean(row.get("yt_product_id"))
        source = clean(row.get("price_source"))
        try:
            price = int(row.get("price_krw") or "")
        except ValueError as exc:
            raise ValueError(f"Invalid reviewed price override: {product_id}") from exc
        if (
            not product_id
            or product_id in overrides
            or price <= 0
            or not source.startswith("https://")
        ):
            raise ValueError(f"Invalid reviewed price override: {product_id}")
        overrides[product_id] = (price, source)
    return overrides


REVIEWED_PRICE_OVERRIDES_BY_ID = reviewed_price_overrides()


def canonical_brand(value: str | None) -> str:
    normalized = key(value)
    visited = set()
    while normalized in BRAND_ALIASES and normalized not in visited:
        visited.add(normalized)
        canonical = BRAND_ALIASES[normalized]
        if canonical == normalized:
            break
        normalized = canonical
    return normalized


def brand_relation(source: str | None, candidate: str | None) -> str:
    """Brand spelling is evidence, not a hard rejection rule."""
    if not known_brand(source) or not known_brand(candidate):
        return "unknown"
    source_key = canonical_brand(source)
    candidate_key = canonical_brand(candidate)
    if source_key == candidate_key or brand_variants(source) & brand_variants(candidate):
        return "same"
    if len(source_key) >= 2 and source_key in candidate_key:
        return "same"
    ratio = difflib.SequenceMatcher(None, source_key, candidate_key).ratio()
    if min(len(source_key), len(candidate_key)) >= 4 and ratio >= 0.82:
        return "similar"
    return "different"


def brand_variants(value: str | None) -> set[str]:
    canonical = canonical_brand(value)
    variants = {key(value), canonical} - {""}
    for part in re.split(r"[()（）]", clean(value)):
        if len(key(part)) >= 3:
            variants.add(key(part))
    for alias in BRAND_ALIASES:
        if canonical_brand(alias) == canonical:
            variants.add(alias)
            variants.add(BRAND_ALIASES[alias])
    for equivalent_group in BRAND_SPELLING_EQUIVALENTS:
        normalized_group = {key(item) for item in equivalent_group}
        if variants & normalized_group:
            variants.update(normalized_group)
    return variants


def product_name_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", clean(value))
    # Remove the SPF group itself, preserving a later bracketed shade.
    text = re.sub(r"\s*[\[(（]\s*SPF\s*\d+[^\])）]*[\])）]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+SPF\s*\d+(?:\+)?(?:\s*/\s*PA\+*)?\s*$", "", text, flags=re.IGNORECASE)
    # A few survey rows accidentally included the product price in the title.
    text = re.sub(r"\s+\d[\d,]*\s*원\s*$", "", text)
    text = text.replace("브러쉬", "브러시").replace("쉐딩", "셰이딩")
    text = text.replace("아이브로우", "브로우")
    # Editorial prefixes and reviewed spelling errors that do not change the
    # product identity.
    text = re.sub(r"^NEW(?=\s|[가-힣A-Z0-9])\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"컨실러\s*펜스", "컨실러 펜슬", text, flags=re.IGNORECASE)
    # Dasique titles use both "싱글 무드 섀도우" and "무드 싱글 섀도우".
    text = re.sub(r"싱글\s*무드\s*섀도우", "무드 싱글 섀도우", text, flags=re.IGNORECASE)
    # Reviewed name spellings and product-family naming variants.
    replacements = (
        ("프로타쥬", "프로타주"),
        ("헤로인메이크", "히로인메이크"),
        ("헤로인 메이크", "히로인메이크"),
        ("롱업", "롱 업"),
        ("워터 프루프", "워터프루프"),
        ("클라우드나인", "클라우드9"),
        ("cloud nine", "cloud 9"),
        ("틴스틱", "틴트"),
        ("퍼팩션", "퍼펙션"),
        ("블랜딩", "블렌딩"),
        ("아트바이로댕", "바이로댕"),
        ("판테베리", "펜타베리"),
        ("퍼펙트테일", "퍼펙테일"),
        ("디파이닝", "디자이닝"),
        # Korean source/candidate labels for the same belif balm variant.
        ("모이스처라이징밤", "모이스처밤"),
        # Common catalog spelling variations found during the v38 review.
        ("내츄럴", "내추럴"),
        ("카밍 인센티브", "카밍 인텐시브"),
        # Explicitly user-confirmed equivalent product-family titles.
        ("편백수 모이스처 부스팅 앰플", "편백 모이스처 앰플"),
        ("스마일링 샌드", "스마일리샌드"),
        ("마시멜로우", "마시멜로"),
        ("피니쉬", "피니시"),
    )
    for old, new in replacements:
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    text = re.sub(r"(바이로댕\s*)피니쉬\s*세팅\s*팩트", r"\1피니쉬 팩트", text)
    text = re.sub(r"커버\s*퍼펙션", "퍼펙션", text)
    text = re.sub(r"(스머징\s*트임\s*)아이라이너", r"\1라이너", text)
    text = re.sub(r"\bROSE\b", "로즈", text, flags=re.IGNORECASE)
    return key(text)


CAMPAIGN_MARKER = re.compile(
    r"(?:에디션|컬렉션|콜라보레이션|콜라보|limited\s+edition|collection|collab(?:oration)?)",
    re.IGNORECASE,
)


def without_campaign_label(value: str) -> str:
    text = unicodedata.normalize("NFKC", clean(value))
    text = re.sub(
        r"[\[(（][^\])）]*(?:에디션|컬렉션|콜라보레이션|콜라보|limited\s+edition|collection|collab(?:oration)?)[^\])）]*[\])）]",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    marker = CAMPAIGN_MARKER.search(text)
    if marker and marker.start() < 50:
        text = text[marker.end() :]
    return clean(text)


def known_brand(value: str | None) -> bool:
    return bool(key(value)) and key(value) not in {"확인필요", "미확인"}


def is_tool(row: dict) -> bool:
    text = " ".join(
        (
            row.get("category") or "",
            row.get("makeup_zone") or "",
            row.get("product_name") or "",
        )
    )
    title = key(row.get("product_name"))
    explicit_false_lash = any(
        token in title
        for token in ("인조속눈썹", "언더래쉬", "언더래시", "가닥속눈썹", "falseeyelash", "falselash")
    )
    if any(token in title for token in ("마스카라", "mascara")) and not explicit_false_lash:
        return False
    return any(
        word in text
        for word in (
            "도구",
            "액세서리",
            "브러시",
            "브러쉬",
            "퍼프",
            "소도구",
            "인조 속눈썹",
            "인조속눈썹",
            "언더래쉬",
            "언더 래쉬",
            "속눈썹",
            "false lashes",
            "false eyelash",
        )
    )


def same_product(row: dict, candidate: dict) -> bool:
    if reviewed_identity_matches(row, candidate):
        return True
    if hard_reject_candidate(row, candidate):
        return False
    source_kind = product_kind(row.get("product_name"))
    candidate_kind = product_kind(candidate.get("name"))
    if source_kind and candidate_kind and source_kind != candidate_kind:
        return False
    return bool(identity_name_variants(row, candidate)) or product_name_score(row, candidate) >= 0.55


def option_key(value: str | None) -> str:
    """Normalize an explicitly recorded shade/option without erasing its value."""
    return re.sub(r"(?<=\d)호", "", product_name_key(value))


def explicit_option_conflict(row: dict, candidate: dict) -> bool:
    """Flag different explicit options; absence of an option on one side is not conflict."""
    source_options = {
        option_key(value)
        for value in (
            row.get("option_name"),
            REVIEWED_PRODUCT_OPTIONS_BY_ID.get(row.get("yt_product_id")),
        )
        if option_key(value)
    }
    candidate_option_values = [
        candidate.get("option_name"),
        *candidate_option_labels(candidate.get("name")),
    ]
    shade_match = re.search(
        r"(?:^|\s)(#?\d{1,3}(?:호|번)?\s*[A-Z가-힣][A-Z0-9가-힣._-]{0,24}|[A-Z]{1,3}\d{1,4})$",
        unicodedata.normalize("NFKC", clean(candidate.get("name"))),
        flags=re.IGNORECASE,
    )
    if shade_match:
        candidate_option_values.append(shade_match.group(1))
    candidate_options = {
        option_key(value)
        for value in candidate_option_values
        if option_key(value)
        and not re.search(
            r"\b(?:spf|pa\+*|ml|g|oz|new|set|gift)\b|에디션|컬렉션|리미티드|한정|기획|증정|리뉴얼|limited|collection",
            clean(value),
            re.IGNORECASE,
        )
    }
    if not candidate_options:
        # The reviewed source specifies shade 2 Fuzzy. A generic product
        # page cannot establish that the image belongs to this shade.
        if row.get("yt_product_id") == "yt-312de8603f36b6de595b" and source_options:
            return True
        return False
    if source_options:
        if source_options & candidate_options:
            return False
        # A source may store only the shade number in option_name while its
        # title contains the same full number and color as the candidate.
        source_title = option_key(clean_source_title(row))
        for source_option in source_options:
            if not re.fullmatch(r"\d{1,3}(?:호|번)?", source_option):
                continue
            if any(
                candidate_option.startswith(source_option)
                and len(candidate_option) > len(source_option)
                and source_title.endswith(candidate_option)
                for candidate_option in candidate_options
            ):
                return False
        return True

    # When the source stores a color in the product title but the candidate
    # stores it in brackets, compare the trailing source text only after an
    # exact, distinctive candidate core. Do not strip arbitrary words.
    source_title = product_name_key(row.get("product_name"))
    for brand in brand_variants(candidate.get("brand")):
        if len(brand) >= 3 and source_title.startswith(brand):
            source_title = source_title[len(brand):]
    candidate_name = candidate.get("name") or ""
    candidate_cores = name_variants(candidate_name, tuple(candidate_option_labels(candidate_name)))
    for core in sorted(candidate_cores, key=len, reverse=True):
        if len(core) < 8 or not source_title.startswith(core):
            continue
        tail = source_title[len(core):]
        if len(tail) >= 2:
            return tail not in candidate_options and not any(
                tail.endswith(option) or option.endswith(tail)
                for option in candidate_options
                if min(len(tail), len(option)) >= 3
            )
    return False


def product_form(value: str | None) -> str:
    """Return only high-confidence product forms used as an auto-match safety gate."""
    text = key(value)
    checks = (
        ("false_lashes", ("언더래쉬", "인조속눈썹", "가닥속눈썹", "속눈썹연장", "falselash")),
        ("curler", ("뷰러", "eyelashcurler", "lashcurler")),
        ("mascara", ("마스카라", "mascara")),
        ("eye_palette", ("아이팔레트", "섀도우팔레트", "섀도팔레트", "eyeshadowpalette")),
        ("eye_pencil", ("프로타주펜슬", "섀도우펜슬", "아이섀도펜슬", "eyepencil")),
        ("cushion", ("쿠션", "cushion")),
    )
    for form, tokens in checks:
        if any(token in text for token in tokens):
            return form
    return ""


def product_form_conflict(row: dict, candidate: dict) -> bool:
    source_form = product_form(row.get("product_name"))
    candidate_form = product_form(candidate.get("name"))
    return bool(source_form and candidate_form and source_form != candidate_form)


def is_lens_candidate(candidate: dict) -> bool:
    brand = key(candidate.get("brand"))
    name = key(candidate.get("name"))
    return "렌즈" in brand or any(term in name for term in ("원데이렌즈", "원먼스", "컬러렌즈"))


def brand_candidate_allowed(row: dict, candidate: dict) -> bool:
    """Reject wrong-brand lookalikes unless the source title names that brand."""
    source_brand = row.get("brand_name")
    candidate_brand = candidate.get("brand")
    if (
        not known_brand(source_brand)
        or not known_brand(candidate_brand)
        or brand_relation(source_brand, candidate_brand) == "same"
    ):
        return True
    source_title = product_name_key(row.get("product_name"))
    return any(
        len(alias) >= 3 and alias in source_title
        for alias in brand_variants(candidate_brand)
    )


def hard_reject_candidate(row: dict, candidate: dict) -> bool:
    """Apply disqualifying evidence consistently to search and review fallbacks."""
    if reviewed_identity_matches(row, candidate):
        return False
    candidate_url = candidate.get("url") or (
        f"https://www.glowpick.com/products/{candidate['product_id']}"
        if candidate.get("product_id")
        else ""
    )
    if candidate_url == REJECTED_CANDIDATE_URLS_BY_SOURCE.get(row.get("yt_product_id")):
        return True
    # CANMAKE's Abloom powder is a separate formula from its regular powder.
    if (
        canonical_brand(row.get("brand_name")) == key("캔메이크")
        and "abloom" in key(row.get("product_name"))
        and "abloom" not in key(candidate.get("name"))
    ):
        return True
    if is_lens_candidate(candidate) or not brand_candidate_allowed(row, candidate):
        return True
    return False


def candidate_option_labels(value: str | None) -> set[str]:
    """Extract option labels from trailing brackets without treating them as product names."""
    raw = unicodedata.normalize("NFKC", clean(value))
    labels: set[str] = set()
    groups = re.findall(r"[\[(（]([^\])）]*)[\])）]", raw)
    for group in groups:
        label = clean(group)
        labels.add(label)
        # Drop shade numbers/codes so source labels such as "오트베이지" can
        # match a catalog option like "#03. 오트베이지".
        color = re.sub(
            r"^(?:(?:no\.?|nº|#)\s*)?\d{1,3}(?:호|번)?(?:[A-Z]{1,3}(?=\s|[.\-_:：]|$))?\s*[.\-_:：]?\s*",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip()
        color = re.sub(r"^[A-Z]{1,3}\d{1,4}\s*", "", color, flags=re.IGNORECASE).strip()
        if color and color != label:
            labels.add(color)
    return {label for label in labels if key(label)}


def strip_option_variant(value: str | None, option: str | None) -> str:
    name_key = product_name_key(value)
    option_key = product_name_key(option)
    if len(option_key) < 2 or len(name_key) <= len(option_key):
        return ""
    if name_key.endswith(option_key):
        return name_key[: -len(option_key)]
    if name_key.startswith(option_key):
        return name_key[len(option_key) :]
    return ""


def identity_name_variants(row: dict, candidate: dict) -> set[str]:
    """Compare product cores after separating source and candidate shade/options."""
    source_name = clean_source_title(row)
    candidate_name = candidate.get("name") or ""
    source_names = [source_name, without_campaign_label(source_name)]
    candidate_names = [candidate_name, without_campaign_label(candidate_name)]
    source_options = [row.get("option_name") or ""]
    reviewed_option = REVIEWED_PRODUCT_OPTIONS_BY_ID.get(row.get("yt_product_id"))
    if reviewed_option:
        source_options.append(reviewed_option)
    candidate_options = candidate_option_labels(candidate_name)

    source_variants = source_name_variants(row)
    candidate_variants = set().union(*(name_variants(name, ()) for name in candidate_names))
    for source_text in source_names:
        for option in (*source_options, *candidate_options):
            source_core = strip_option_variant(source_text, option)
            if source_core:
                source_variants.add(source_core)
    for candidate_text in candidate_names:
        for option in (*source_options, *candidate_options):
            candidate_core = strip_option_variant(candidate_text, option)
            if candidate_core:
                candidate_variants.add(candidate_core)

    # If a candidate brand is written explicitly at the beginning of the
    # source title, remove it before comparing the product core.
    for brand in brand_variants(candidate.get("brand")):
        if len(brand) < 3:
            continue
        for source_text in source_names:
            source_key = product_name_key(source_text)
            if source_key.startswith(brand) and len(source_key) > len(brand):
                source_variants.add(source_key[len(brand) :])
                for option in candidate_options:
                    source_core = strip_option_variant(source_text[len(brand) :], option)
                    if source_core:
                        source_variants.add(source_core)

    matching = source_variants & candidate_variants
    # Unbracketed numbered shades can be written without the number in the
    # source. Require the same distinctive product core AND the same shade
    # text; merely sharing a product family is insufficient.
    match = re.search(
        r"\s+\d{1,3}(?:호|번)?\s+([A-Z가-힣][A-Z가-힣\s-]{1,30})$",
        candidate_name,
        flags=re.IGNORECASE,
    )
    if match and brand_relation(row.get("brand_name"), candidate.get("brand")) == "same":
        color = product_name_key(match.group(1))
        candidate_core = product_name_key(candidate_name[:match.start()])
        for source_variant in source_variants:
            if (
                len(candidate_core) >= 9
                and len(color) >= 3
                and source_variant == candidate_core + color
            ):
                matching.add(candidate_core)
    return matching


def product_kind(value: str | None) -> str:
    text = key(value)
    if any(token in text for token in ("뷰러", "eyelashcurler", "lashcurler")):
        return "curler"
    if any(
        token in text
        for token in (
            "언더래쉬",
            "인조속눈썹",
            "가닥속눈썹",
            "속눈썹연장",
            "falseeyelash",
            "falselashes",
            "fakelash",
        )
    ):
        return "false_lashes"
    if "마스카라" in text or "mascara" in text:
        return "mascara"
    return ""


def tool_model_code(value: str | None) -> str:
    """Return an explicit brush model number when it is adjacent to brush text."""
    text = unicodedata.normalize("NFKC", clean(value)).casefold()
    patterns = (
        r"(?<![a-z0-9])(\d{1,3}[a-z]?)(?=\s*(?:쉐이딩|셰이딩|립|아이|블러셔)?\s*(?:브러쉬|브러시|brush))",
        r"(?:브러쉬|브러시|brush)\s*(\d{1,3}[a-z]?)(?![a-z0-9])",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).casefold()
    return ""


def product_kinds_compatible(source: str | None, candidate: str | None) -> bool:
    source_kind = product_kind(source)
    candidate_kind = product_kind(candidate)
    return not source_kind or not candidate_kind or source_kind == candidate_kind


def product_name_score(row: dict, candidate: dict) -> float:
    """Similarity used to rank search results, not by itself to confirm identity."""
    source_variants = source_name_variants(row)
    found_variants = name_variants(candidate.get("name"), ())
    source_variants.update(identity_name_variants(row, candidate))
    found_variants.update(identity_name_variants(row, candidate))
    if not source_variants or not found_variants:
        return 0.0
    for brand in (row.get("brand_name"), candidate.get("brand")):
        for variant in brand_variants(brand):
            source_variants.update(
                source[len(variant) :]
                for source in tuple(source_variants)
                if source.startswith(variant) and len(source) > len(variant)
            )
    if source_variants.intersection(found_variants):
        return 1.0
    return max(
        difflib.SequenceMatcher(None, source, found).ratio()
        for source in source_variants
        for found in found_variants
    )


def name_variants(value: str | None, options: tuple[str, ...] | list[str]) -> set[str]:
    """Normalize names and remove only explicit or strongly delimited option suffixes."""
    raw = unicodedata.normalize("NFKC", clean(value))
    if not raw:
        return set()
    variants = {product_name_key(raw)}
    # Shade, SPF, and package notes are commonly appended in one or more
    # bracketed groups. Compare the shared product title after removing only
    # complete trailing groups; keep the original full name as evidence too.
    bracket_core = raw
    while True:
        shortened = re.sub(r"\s*[\[(（][^\])）]*[\])）]\s*$", "", bracket_core).strip()
        if not shortened or shortened == bracket_core:
            break
        variants.add(product_name_key(shortened))
        bracket_core = shortened
    campaign_cleaned = without_campaign_label(raw)
    if campaign_cleaned != raw:
        variants.add(product_name_key(campaign_cleaned))
    for option in options:
        option_text = unicodedata.normalize("NFKC", clean(option))
        if option_text and raw.casefold().endswith(option_text.casefold()):
            base = raw[: -len(option_text)].rstrip(" _#/:-")
            if base:
                variants.add(product_name_key(base))

    # Underscore and hash are explicit separators in the source file's option labels.
    delimited = re.sub(r"\s*[_#]\s*[^_#]+$", "", raw).strip()
    if delimited and delimited != raw:
        variants.add(product_name_key(delimited))

    wrapped = re.sub(
        r"\s*[\[(（]\s*(?:#?\d{1,3}(?:호|번)?\b|SPF\s*\d+)[^\])）]*[\])）]\s*$",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    if wrapped and wrapped != raw:
        variants.add(product_name_key(wrapped))

    # Numbered shade codes are strong signals; arbitrary final words are not stripped.
    coded = re.sub(
        r"(?:\s|[_#])(?:\d{1,3}(?:호|번)?\s*[A-Z가-힣][A-Z0-9가-힣._-]{0,24}|[A-Z]{1,3}\d{1,4})$",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    if coded and coded != raw:
        variants.add(product_name_key(coded))
        # Some source titles concatenate multiple shade names. Remove a
        # sequence of explicit numbered shade suffixes to recover the base.
        shade_core = coded
        while True:
            shorter = re.sub(
                r"(?:\s|[_#])(?:\d{1,3}(?:호|번)?\s*[A-Z가-힣][A-Z0-9가-힣._-]{0,24}|[A-Z]{1,3}\d{1,4})$",
                "",
                shade_core,
                flags=re.IGNORECASE,
            ).strip()
            if not shorter or shorter == shade_core:
                break
            variants.add(product_name_key(shorter))
            shade_core = shorter
    numbered_shade = re.sub(r"(?:\s|[_#])\d{1,3}호$", "", delimited).strip()
    if numbered_shade and numbered_shade != delimited:
        variants.add(product_name_key(numbered_shade))
    return {item for item in variants if item}


def exact_product_cores(value: str | None) -> set[str]:
    """Return exact title cores after removing explicit terminal shade labels."""
    raw = unicodedata.normalize("NFKC", clean(value))
    if not raw:
        return set()
    cores = {product_name_key(raw)}
    current = raw
    for _ in range(8):
        shortened = re.sub(r"\s*[\[(（][^\])）]*[\])）]\s*$", "", current).strip()
        if shortened == current:
            shortened = re.sub(
                r"(?:\s|[_#])(?:\d{1,3}(?:호|번)?\s*[A-Z가-힣][A-Z0-9가-힣._-]{0,24}|[A-Z]{1,3}\d{1,4})$",
                "",
                current,
                flags=re.IGNORECASE,
            ).strip()
        if not shortened or shortened == current:
            break
        cores.add(product_name_key(shortened))
        current = shortened
    return cores


def candidate_identity_compatible(current: dict, candidate: dict) -> bool:
    if brand_relation(current.get("brand"), candidate.get("brand")) != "same":
        return False
    if explicit_volume_conflict(current.get("volume"), candidate.get("volume")):
        return False
    a = name_variants(current.get("name"), ())
    b = name_variants(candidate.get("name"), ())
    return bool(a & b) or max(
        (difflib.SequenceMatcher(None, left, right).ratio() for left in a for right in b),
        default=0.0,
    ) >= 0.94


def explicit_volume_conflict(left: str | None, right: str | None) -> bool:
    """Different explicit package sizes must not share price or image data."""
    amount = re.compile(r"(?<![A-Za-z])(?P<n>\d+(?:\.\d+)?)\s*(?P<u>ml|g|kg|oz)\b", re.I)

    def one_size(value: str | None) -> tuple[str, float] | None:
        matches = {(match.group("u").casefold(), float(match.group("n"))) for match in amount.finditer(value or "")}
        if len(matches) != 1:
            return None
        return next(iter(matches))

    first, second = one_size(left), one_size(right)
    return bool(first and second and first[0] == second[0] and first[1] != second[1])


def same_candidate_url(current: dict, candidate: dict) -> bool:
    return bool(current.get("url") and current["url"] == candidate.get("url"))


def unknown_brand_exact_core(row: dict, candidate: dict) -> bool:
    """Allow a missing source brand only when a distinctive product core matches."""
    if known_brand(row.get("brand_name")) or not known_brand(candidate.get("brand")):
        return False
    if not product_kinds_compatible(row.get("product_name"), candidate.get("name")):
        return False
    source_category = category_tag(row)
    candidate_category = category_tag(
        {"category": "", "makeup_zone": "", "product_name": candidate.get("name") or ""}
    )
    if (
        source_category != "unknown"
        and candidate_category != "unknown"
        and source_category != candidate_category
        and source_category != "tool"
    ):
        return False
    source_variants = source_name_variants(row)
    candidate_variants = name_variants(candidate.get("name"), ())
    source_variants.update(identity_name_variants(row, candidate))
    candidate_variants.update(identity_name_variants(row, candidate))
    candidate_brands = brand_variants(candidate.get("brand"))
    for brand in candidate_brands:
        source_variants.update(
            source[len(brand) :]
            for source in tuple(source_variants)
            if source.startswith(brand) and len(source) > len(brand)
        )
        candidate_variants.update(
            name[len(brand) :]
            for name in tuple(candidate_variants)
            if name.startswith(brand) and len(name) > len(brand)
        )

    # If the source brand column is unknown but the title itself begins with
    # the candidate's brand (for example "chica-y-chico: 원샷 아이팔레트" or
    # "Dinto: 딘토 소프트글로우 리퀴드 치크"), permit an exact, distinctive
    # product-title match after removing only that explicit brand prefix.
    # This handles confirmed brand-prefixed titles without lowering the
    # general 9-character threshold for otherwise unbranded source names.
    brand_prefixes = set(candidate_brands)
    for part in re.split(r"[()（）:：|｜]", clean(candidate.get("brand"))):
        normalized = key(part)
        if len(normalized) >= 2:
            brand_prefixes.add(normalized)
    prefixed_cores = set()
    pending = list(source_variants)
    visited = set()
    while pending:
        value = pending.pop()
        if value in visited:
            continue
        visited.add(value)
        for brand in brand_prefixes:
            if value.startswith(brand) and len(value) > len(brand):
                remainder = value[len(brand) :]
                prefixed_cores.add(remainder)
                pending.append(remainder)
    for core in prefixed_cores & candidate_variants:
        descriptor = core
        for term in sorted(GENERIC_PRODUCT_TERMS, key=len, reverse=True):
            descriptor = descriptor.replace(term, "")
        if len(core) >= 7 and len(descriptor) >= 3:
            return True

    matching_cores = source_variants & candidate_variants
    matching_cores.update(
        exact_product_cores(row.get("product_name"))
        & exact_product_cores(candidate.get("name"))
    )
    for core in matching_cores:
        # Unknown-brand rows require an exact core of at least 9 normalized
        # characters plus a distinctive descriptor beyond its product type.
        # Thus "핑크 에버라스팅 앰플" can pass while short/generic names cannot.
        if core == product_name_key("세라마이드 샷 앰플"):
            return True
        if len(core) < 9:
            continue
        descriptor = core
        for term in sorted(GENERIC_PRODUCT_TERMS, key=len, reverse=True):
            descriptor = descriptor.replace(term, "")
        if len(descriptor) >= 3:
            return True
    return False


def auto_identity_confident(row: dict, candidate: dict) -> bool:
    if is_lens_candidate(candidate):
        return False
    if reviewed_identity_matches(row, candidate):
        return True
    if is_tool(row):
        source_code = tool_model_code(row.get("product_name"))
        candidate_code = tool_model_code(candidate.get("name"))
        if source_code and candidate_code and source_code != candidate_code:
            return False
    if product_form_conflict(row, candidate) or explicit_option_conflict(row, candidate):
        return False
    if known_brand(row.get("brand_name")):
        if not brand_candidate_allowed(row, candidate):
            return False
        return bool(identity_name_variants(row, candidate)) or product_name_score(row, candidate) >= 0.94
    return unknown_brand_exact_core(row, candidate)


def clean_source_title(row: dict) -> str:
    name = unicodedata.normalize("NFKC", clean(row.get("product_name")))
    name = re.sub(
        r"\s*\*+\s*\d{1,2}월\s*중\s*['\"]?출시\s*예정['\"]?\s*\*+\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    brand = key(row.get("brand_name"))
    if brand.startswith(key("돌체앤가바나")):
        name = re.sub(r"^\s*&\s*GABBANA\)\s*뷰티\s*[-:：]\s*", "", name, flags=re.IGNORECASE)
    if brand.startswith(key("글린트")):
        name = re.sub(r"^\s*바이\s*비디보브\s+", "", name)
    return name


def source_name_variants(row: dict) -> set[str]:
    options = [row.get("option_name") or ""]
    reviewed = REVIEWED_PRODUCT_OPTIONS_BY_ID.get(row.get("yt_product_id"))
    if reviewed:
        options.append(reviewed)
    name = clean_source_title(row)
    variants = name_variants(name, options)
    # The source file sometimes prefixes ETUDE products with "house" even
    # though the brand is already stored separately as ETUDE. Treat that
    # brand extension as metadata only for ETUDE rows.
    if canonical_brand(row.get("brand_name")) == key("에뛰드"):
        shortened = re.sub(r"^\s*(?:에뛰드\s*)?하우스\s+", "", name, flags=re.IGNORECASE)
        shortened = re.sub(r"^\s*house\s+", "", shortened, flags=re.IGNORECASE)
        if shortened != name:
            variants.update(name_variants(shortened, options))
    if key(row.get("brand_name")) in {key("캔메이크"), key("CANMAKE")}:
        shortened = re.sub(r"^\s*TOKYO\s+", "", name, flags=re.IGNORECASE)
        if shortened != name:
            variants.update(name_variants(shortened, options))
    return variants


def category_tag(row: dict, external_category: str = "") -> str:
    if is_tool(row):
        return "tool"
    if "스킨틴트" in key(row.get("product_name")):
        return "base"
    category = row.get("category") or ""
    makeup_zone = row.get("makeup_zone") or ""
    name = row.get("product_name") or ""
    external_key = key(external_category)
    if any(
        term in external_key
        for term in (
            "아이메이크업", "아이섀도", "아이팔레트", "마스카라",
            "아이라이너", "아이브로우",
        )
    ):
        return "eye"
    if any(term in external_key for term in ("립메이크업", "립스틱", "립틴트", "립글로스")):
        return "lip"
    if any(term in external_key for term in ("스킨케어", "클렌징", "클렌저", "토너", "에센스", "앰플", "세럼")):
        return "skincare"
    if any(term in external_key for term in ("블러셔", "치크", "블러시")):
        return "cheek"
    if any(term in external_key for term in ("선케어", "선크림", "선스틱")):
        return "suncare"
    if clean(external_category) in {"크림", "아이크림", "수분크림", "에멀전"}:
        return "skincare"
    if clean(external_category) in {"파우더/팩트", "프라이머", "메이크업베이스"}:
        return "base"
    for raw in (external_category, category, makeup_zone, name):
        if any(word in raw for word in ("선케어", "선크림", "선스틱", "자외선")):
            return "suncare"
        if any(word in raw for word in ("립", "입술", "틴트", "lip", "lipstick")):
            return "lip"
        if any(
            word in raw
            for word in ("치크", "블러셔", "쉐딩", "컨투어", "하이라이터", "하이라이트펜", "blush")
        ):
            return "cheek"
        if "블러쉬" in raw:
            return "cheek"
        if any(word in raw for word in ("베이스", "쿠션", "파운데이션", "컨실러", "foundation")):
            return "base"
        if any(word in raw for word in ("파우더브로우", "파우더 브로우")):
            return "eye"
        if any(
            word in raw
            for word in ("파우더", "프레스드 파우더", "루스 파우더", "pressed powder")
        ):
            return "base"
        if any(word in raw for word in ("샤워 펜슬", "샤워펜슬")):
            return "eye"
        if any(
            word in raw
            for word in (
                "진정크림", "리페어크림", "리페어 크림", "모이스처밤",
                "모이스처라이징밤", "모이스처라이징 밤", "더트루크림",
                "더 트루 크림",
            )
        ):
            return "skincare"
        if any(word in raw for word in ("선젤", "선 젤")):
            return "suncare"
        if "글로스" in raw or "gloss" in raw:
            return "lip"
        if any(
            word in raw
            for word in (
                "아이", "눈", "속눈썹", "아이라인", "아이라이너", "라이너",
                "브로우", "아이브로우", "섀도", "마스카라", "eyeliner",
                "mascara", "eyeshadow", "eyebrow", "eye palette",
            )
        ):
            return "eye"
        if any(
            word in raw
            for word in (
                "스킨케어", "앰플", "세럼", "마스크", "토너", "클렌징", "클렌저",
                "클렌징폼", "수딩크림", "패드", "에센스", "로션", "serum",
                "cleanser", "toner",
            )
        ):
            return "skincare"
    return "unknown"


def source_queries(row: dict) -> list[str]:
    name = clean_source_title(row)
    display_names = [name]
    source_option = clean(row.get("option_name"))
    if source_option and option_key(source_option) not in option_key(name):
        display_names.insert(0, clean(f"{name} {source_option}"))
        if canonical_brand(row.get("brand_name")) == key("투쿨포스쿨"):
            display_names.insert(
                0,
                clean(f"{name} {source_option}").replace(
                    "스머징 트임 아이라이너", "스머징 트임 라이너"
                ),
            )
    brand_key = canonical_brand(row.get("brand_name"))
    if brand_key == key("캔메이크"):
        without_tokyo = re.sub(r"^\s*TOKYO\s+", "", name, flags=re.IGNORECASE)
        display_names.append(without_tokyo)
        display_names.append(
            re.sub(r"\s*\d{1,2}\s*Abloom\s*$", " Abloom", without_tokyo, flags=re.IGNORECASE)
        )
    if brand_key == key("쉬글램") and "투인원" in name:
        display_names.append(
            name.replace("파인라인", "파인 라인")
            .replace("투인원", "2in1")
            .replace("컨투어 하이라이트펜", "컨투어 앤 하이라이트")
        )
    options = [row.get("option_name") or ""]
    reviewed = REVIEWED_PRODUCT_OPTIONS_BY_ID.get(row.get("yt_product_id"))
    if reviewed:
        options.append(reviewed)
    for option in options:
        option = unicodedata.normalize("NFKC", clean(option))
        if option and name.casefold().endswith(option.casefold()):
            base = name[: -len(option)].rstrip(" _#/:-")
            if base:
                display_names.append(base)
    for pattern in (
        r"\s*[_#]\s*[^_#]+$",
        r"(?:\s|[_#])(?:\d{1,3}(?:호|번)?\s*[A-Z가-힣][A-Z0-9가-힣._-]{0,24}|[A-Z]{1,3}\d{1,4})$",
    ):
        base = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
        if base and base != name:
            display_names.append(base)
    display_names = list(dict.fromkeys(clean(item).replace("_", " ") for item in display_names))
    brand = clean(row.get("brand_name"))
    if brand.count("(") > brand.count(")"):
        brand = clean(brand.split("(", 1)[0])
    brands = [brand] if known_brand(brand) else []
    canonical = canonical_brand(brand)
    canonical_display = BRAND_SEARCH_NAMES.get(canonical)
    if canonical_display and key(canonical_display) not in {key(item) for item in brands}:
        brands.append(canonical_display)

    queries: list[str] = []
    for product_name in display_names:
        product_name = clean(product_name).replace("_", " ")
        for brand_name in brands:
            queries.append(clean(f"{brand_name} {product_name}"))
        queries.append(product_name)
    result: list[str] = []
    seen = set()
    for query in queries:
        normalized = key(query)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(query)
    return result[:6]


def valid_image(value: str | None) -> str:
    return value if value and value.startswith("https://") else ""


def retry_http_5xx(operation, label: str, waits=HTTP_5XX_RETRY_SECONDS):
    status = 0
    for attempt, wait in enumerate((0, *waits)):
        try:
            if wait:
                print(
                    f"{label} 재시도 대기 {wait}초 "
                    f"({attempt}/{len(waits)}); "
                    f"직전 응답 HTTP {status}",
                    flush=True,
                )
                time.sleep(wait)
            return operation()
        except (httpx.HTTPStatusError, requests.HTTPError) as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", 0)
            if 500 <= status <= 599:
                headers = getattr(response, "headers", {}) or {}
                body = getattr(response, "text", "") or ""
                body = unescape(re.sub(r"<[^>]+>", " ", body))
                body = clean(body)[:240] or "(응답 본문 없음)"
                request_id = (
                    headers.get("x-request-id")
                    or headers.get("x-correlation-id")
                    or headers.get("trace-id")
                    or "없음"
                )
                response_url = getattr(response, "url", None)
                path = getattr(response_url, "path", "경로 확인 불가")
                print(
                    f"{label} 오류 상세: HTTP {status}; path={path}; "
                    f"content-type={headers.get('content-type', '없음')}; "
                    f"server={headers.get('server', '없음')}; "
                    f"request-id={request_id}; body={body}",
                    flush=True,
                )
            if not 500 <= status <= 599 or attempt == len(waits):
                raise
    raise AssertionError("unreachable")


class Blocked(RuntimeError):
    pass


class OptionalSourceBlocked(Blocked):
    """An optional source blocked requests; continue with the other sources."""


class SiteClient:
    """Thread-safe site-wide pacing and shared 1, 3, 10 minute cooldown."""

    def __init__(self, name: str, delay: float):
        self.name = name
        self.delay = delay
        self.condition = threading.Condition()
        self.next_at = 0.0
        self.blocked_until = 0.0
        self.block_round = 0
        self.stopped = False
        self.source_unavailable = False
        self.local = threading.local()
        self.sessions: list[requests.Session] = []
        self.session_lock = threading.Lock()
        self.client = (
            None
            if name == "Olive Young"
            else httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
                timeout=25,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
            )
        )

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        with self.session_lock:
            for session in self.sessions:
                session.close()

    def stop(self) -> None:
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def _request(self, url: str) -> httpx.Response | requests.Response:
        if self.client is not None:
            return self.client.get(url)
        session = getattr(self.local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                    "Referer": "https://m.oliveyoung.co.kr/",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,*/*;q=0.8"
                    ),
                }
            )
            self.local.session = session
            with self.session_lock:
                self.sessions.append(session)
        return session.get(url, timeout=20)

    def get(self, url: str) -> httpx.Response | requests.Response:
        server_error_attempt = 0
        while True:
            with self.condition:
                if self.stopped:
                    error = OptionalSourceBlocked if self.source_unavailable else Blocked
                    raise error(f"{self.name} 요청 중단")
                while time.monotonic() < max(self.next_at, self.blocked_until):
                    self.condition.wait(timeout=5)
                    if self.stopped:
                        error = OptionalSourceBlocked if self.source_unavailable else Blocked
                        raise error(f"{self.name} 요청 중단")
                self.next_at = time.monotonic() + self.delay
            response = self._request(url)
            if 500 <= response.status_code <= 599:
                if server_error_attempt >= len(HTTP_5XX_RETRY_SECONDS):
                    response.raise_for_status()
                wait = HTTP_5XX_RETRY_SECONDS[server_error_attempt]
                server_error_attempt += 1
                print(
                    f"{self.name} HTTP {response.status_code}; {wait}초 후 재시도 "
                    f"({server_error_attempt}/{len(HTTP_5XX_RETRY_SECONDS)})",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if response.status_code not in {403, 429}:
                if response.status_code < 400:
                    with self.condition:
                        if time.monotonic() >= self.blocked_until:
                            self.block_round = 0
                response.raise_for_status()
                response.encoding = "utf-8"
                return response
            if self.name == "Olive Young":
                with self.condition:
                    if not self.source_unavailable:
                        print(
                            f"Olive Young HTTP {response.status_code}; 이번 실행의 올영 요청을 "
                            "중단하고 글로우픽·화해로 계속 진행",
                            flush=True,
                        )
                    self.source_unavailable = True
                    self.stopped = True
                    self.condition.notify_all()
                raise OptionalSourceBlocked(f"Olive Young HTTP {response.status_code}")
            with self.condition:
                if time.monotonic() < self.blocked_until:
                    continue
                if self.block_round >= len(WAIT_SECONDS):
                    self.stopped = True
                    self.condition.notify_all()
                    raise Blocked(
                        f"{self.name} HTTP {response.status_code}: 1·3·10분 후에도 차단"
                    )
                wait = WAIT_SECONDS[self.block_round]
                self.block_round += 1
                self.blocked_until = time.monotonic() + wait
                print(
                    f"{self.name} HTTP {response.status_code}; 전체 작업자 {wait // 60}분 대기 "
                    f"({self.block_round}/3)",
                    flush=True,
                )
                self.condition.notify_all()


def glowpick_detail(glowpick: GlowpickClient, product_id: int, search_brand: str) -> dict:
    url = f"https://www.glowpick.com/products/{product_id}"

    def fetch_detail():
        response = glowpick._request("GET", url)
        response.raise_for_status()
        return response

    response = retry_http_5xx(fetch_detail, "Glowpick detail")
    response.encoding = "utf-8"
    parsed = _parse_detail(response.text, product_id)
    parser = DetailParser()
    parser.feed(response.text)
    image = valid_image(parser.meta.get("og:image"))
    volume_match = re.search(
        r'class="[^"]*volume[^"]*"[^>]*>\s*([^<]+)', response.text, re.IGNORECASE
    )
    volume = clean(unescape(volume_match.group(1))) if volume_match else ""
    return {
        "brand": parsed["brand"] or search_brand,
        "name": parsed["name"],
        "url": f"https://www.glowpick.com/products/{product_id}",
        "price": parsed["price"],
        "volume": volume,
        "image": image,
        "site": "glowpick",
    }


def glowpick_search_page_candidates(
    glowpick: GlowpickClient, query: str, limit: int = 12
) -> list[dict]:
    """Use browser-visible product links when Glowpick's search API fails."""
    html = retry_http_5xx(
        lambda: glowpick.search_page(query), f"Glowpick browser search query={query!r}"
    )
    product_ids = list(
        dict.fromkeys(
            int(match)
            for match in re.findall(
                r"(?:https?://(?:www\.)?glowpick\.com)?/products/(\d+)(?:/|[?#\"'])",
                html,
                flags=re.IGNORECASE,
            )
        )
    )[:limit]
    candidates = []
    for product_id in product_ids:
        try:
            detail = glowpick_detail(glowpick, product_id, "")
        except (httpx.HTTPError, requests.RequestException, ValueError) as exc:
            print(
                f"Glowpick browser search detail failed: product_id={product_id}; "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        candidates.append(
            {
                "product_id": product_id,
                "name": detail.get("name") or "",
                "brand": detail.get("brand") or "",
                "price": detail.get("price"),
                "candidate_source": "product_search",
            }
        )
    print(
        f"Glowpick browser search fallback: query={query!r}; "
        f"product_links={len(product_ids)}; details={len(candidates)}",
        flush=True,
    )
    return candidates


class GlowpickCategoryParser(HTMLParser):
    """Read the visible category path from Glowpick's product details page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_category_list = False
        self.li_depth = 0
        self.current_text: list[str] = []
        self.categories: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "ul" and "categoryList" in (attrs.get("class") or ""):
            self.in_category_list = True
        elif self.in_category_list and tag == "li":
            if self.li_depth == 0:
                self.current_text = []
            self.li_depth += 1

    def handle_data(self, data):
        if self.in_category_list and self.li_depth:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if not self.in_category_list:
            return
        if tag == "li" and self.li_depth:
            self.li_depth -= 1
            if self.li_depth == 0:
                value = clean(" ".join(self.current_text))
                if value:
                    self.categories.append(value)
        elif tag == "ul" and not self.li_depth:
            self.in_category_list = False


def glowpick_categories(glowpick: GlowpickClient, product_id: int) -> list[str]:
    url = f"https://www.glowpick.com/products/{product_id}/details"

    def fetch_categories():
        response = glowpick._request("GET", url)
        response.raise_for_status()
        return response

    response = retry_http_5xx(fetch_categories, "Glowpick category")
    response.encoding = "utf-8"
    parser = GlowpickCategoryParser()
    parser.feed(response.text)
    return parser.categories


def search_glowpick(row: dict, glowpick: GlowpickClient) -> dict | None:
    candidates_by_id: dict[int, dict] = {}
    last_server_error = None
    server_failures = 0
    browser_fallback_used = False
    for query in sorted(source_queries(row), key=len):
        try:
            candidates = retry_http_5xx(
                lambda query=query: glowpick.search(query),
                f"Glowpick search query={query!r}",
                waits=(5,),
            )
        except (httpx.HTTPStatusError, requests.HTTPError) as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", 0)
            if not 500 <= status <= 599:
                raise
            server_failures += 1
            candidates = []
            if not browser_fallback_used:
                browser_fallback_used = True
                print(
                    f"Glowpick search API still failing (HTTP {status}); "
                    "trying browser-facing search page",
                    flush=True,
                )
                candidates = glowpick_search_page_candidates(glowpick, query)
            if not candidates:
                print(
                    "Glowpick API and browser search both yielded no candidates; "
                    "trying the next query or falling through to Hwahae",
                    flush=True,
                )
                last_server_error = exc
                if server_failures >= 2:
                    break
                continue
        for candidate in candidates:
            product_id = candidate.get("product_id")
            if not product_id:
                continue
            previous = candidates_by_id.get(product_id)
            if previous is None:
                candidates_by_id[product_id] = dict(candidate)
                continue
            sources = set(previous.get("candidate_source", "").split("+"))
            sources.update(candidate.get("candidate_source", "").split("+"))
            previous["candidate_source"] = "+".join(
                source
                for source in ("product_search", "review_tag")
                if source in sources
            )
            for field in ("name", "brand", "price"):
                if not previous.get(field) and candidate.get(field):
                    previous[field] = candidate[field]
        strong_direct = [
            candidate
            for candidate in candidates_by_id.values()
            if "product_search" in candidate.get("candidate_source", "")
            and auto_identity_confident(row, candidate)
        ]
        if known_brand(row.get("brand_name")) and len(strong_direct) == 1:
            break

    if not candidates_by_id and last_server_error is not None:
        raise last_server_error

    exact_brands = [
        candidate.get("brand")
        for candidate in candidates_by_id.values()
        if unknown_brand_exact_core(row, candidate)
    ]
    ambiguous_unknown_brand = bool(exact_brands) and any(
        brand_relation(exact_brands[0], brand) != "same"
        for brand in exact_brands[1:]
    )

    # Rank by identity evidence before the search-result section. A weak first
    # product result must not hide an exact review-tagged product.
    def rank(candidate: dict) -> tuple[int, int, float, int]:
        sources = set(candidate.get("candidate_source", "").split("+"))
        direct_priority = 0 if "product_search" in sources else 1
        brand_priority = {"same": 0, "similar": 1, "unknown": 2, "different": 3}[
            brand_relation(row.get("brand_name"), candidate.get("brand"))
        ]
        return (
            0 if auto_identity_confident(row, candidate) else 1,
            brand_priority,
            -product_name_score(row, candidate),
            direct_priority,
        )

    review_fallback = None
    for candidate in sorted(candidates_by_id.values(), key=rank):
        if hard_reject_candidate(row, candidate):
            continue
        sources = set(candidate.get("candidate_source", "").split("+"))
        is_same_product = same_product(row, candidate)
        if not is_same_product:
            form_conflict = product_form_conflict(row, candidate) or not product_kinds_compatible(
                row.get("product_name"), candidate.get("name")
            )
            if "review_tag" not in sources and not form_conflict:
                continue
            if product_name_score(row, candidate) < 0.55:
                continue
        detail = glowpick_detail(
            glowpick, candidate["product_id"], candidate.get("brand") or ""
        )
        detail["candidate_source"] = candidate.get("candidate_source", "")
        if same_product(row, detail):
            if auto_identity_confident(row, detail):
                if ambiguous_unknown_brand and not known_brand(row.get("brand_name")):
                    detail["match_basis"] = "unknown_brand_ambiguous"
                    if review_fallback is None:
                        review_fallback = detail
                    continue
                if "review_tag" in sources and "product_search" not in sources:
                    detail["match_basis"] = "review_tag_exact"
                return detail
            if review_fallback is None:
                detail["match_basis"] = (
                    "review_tag_fallback" if "product_search" not in sources
                    else "product_search_review"
                )
                review_fallback = detail
            continue
        if (
            review_fallback is None
            and (
                product_form_conflict(row, detail)
                or not product_kinds_compatible(row.get("product_name"), detail.get("name"))
            )
            and product_name_score(row, detail) >= 0.55
        ):
            detail["match_basis"] = "product_form_conflict"
            review_fallback = detail
            continue
        if (
            "review_tag" in sources
            and review_fallback is None
            and product_kinds_compatible(row.get("product_name"), detail.get("name"))
            and product_name_score(row, detail) >= 0.55
        ):
            detail["match_basis"] = "review_tag_fallback"
            review_fallback = detail
    return review_fallback


def search_hwahae(row: dict, client: SiteClient) -> dict | None:
    review_candidate = None
    review_score = -1.0
    exact_candidates: dict[str, dict] = {}
    for query in source_queries(row):
        url = "https://www.hwahae.co.kr/search?" + urlencode(
            {"q": query, "type": "products"}
        )
        body = client.get(url).text
        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.DOTALL
        )
        if not match:
            continue
        data = json.loads(match.group(1))
        items = (
            data.get("props", {})
            .get("pageProps", {})
            .get("products", {})
            .get("products", [])
        )
        if not items:
            continue
        candidates = [item for item in items if item.get("id")]

        def rank(item: dict) -> tuple[int, float]:
            brand = item.get("brand") or ""
            if isinstance(brand, dict):
                brand = brand.get("name") or brand.get("brandName") or ""
            brand_match = {"same": 0, "similar": 1, "unknown": 2, "different": 3}[
                brand_relation(row["brand_name"], brand)
            ]
            return (
                brand_match,
                -product_name_score(row, {"name": item.get("productName")}),
            )

        for item in sorted(candidates, key=rank):
            brand = item.get("brand") or ""
            if isinstance(brand, dict):
                brand = brand.get("name") or brand.get("brandName") or ""
            candidate = {
                "brand": clean(brand),
                "name": clean(item.get("productName")),
                "url": f"https://www.hwahae.co.kr/products/{item['id']}",
            }
            if hard_reject_candidate(row, candidate):
                continue
            is_same_product = same_product(row, candidate)
            form_conflict = product_form_conflict(row, candidate) or not product_kinds_compatible(
                row.get("product_name"), candidate.get("name")
            )
            score = product_name_score(row, candidate)
            if not is_same_product and (not form_conflict or score < 0.55):
                continue
            price = item.get("product_price")
            candidate.update({
                "price": int(price) if price and int(price) > 0 else None,
                "volume": clean(item.get("product_capacity")),
                "image": valid_image(item.get("imageUrl")),
                "site": "hwahae",
            })
            if not is_same_product and form_conflict:
                candidate["match_basis"] = "product_form_conflict"
            elif auto_identity_confident(row, candidate):
                if known_brand(row.get("brand_name")):
                    return candidate
                exact_candidates[candidate["url"]] = candidate
                continue
            score = product_name_score(row, candidate)
            if score > review_score:
                review_candidate = candidate
                review_score = score
    if exact_candidates:
        matches = list(exact_candidates.values())
        first_brand = matches[0]["brand"]
        if any(brand_relation(first_brand, item["brand"]) != "same" for item in matches[1:]):
            matches[0]["match_basis"] = "unknown_brand_ambiguous"
        return matches[0]
    return review_candidate


def reviewed_hwahae_detail(client: SiteClient, product_id: int, query: str) -> dict | None:
    """Find one human-verified Hwahae ID; never substitute a different result."""
    url = "https://www.hwahae.co.kr/search?" + urlencode({"q": query, "type": "products"})
    body = client.get(url).text
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.DOTALL)
    if not match:
        return None
    data = json.loads(match.group(1))
    items = (
        data.get("props", {})
        .get("pageProps", {})
        .get("products", {})
        .get("products", [])
    )
    for item in items:
        if str(item.get("id")) != str(product_id):
            continue
        brand = item.get("brand") or ""
        if isinstance(brand, dict):
            brand = brand.get("name") or brand.get("brandName") or ""
        price = item.get("product_price")
        return {
            "brand": clean(brand),
            "name": clean(item.get("productName")),
            "url": f"https://www.hwahae.co.kr/products/{product_id}",
            "price": int(price) if price and int(price) > 0 else None,
            "volume": clean(item.get("product_capacity")),
            "image": valid_image(item.get("imageUrl")),
            "site": "hwahae",
        }
    return None


def _powderroom_image(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("https://"):
        return value
    path = value.lstrip("/")
    return f"https://newimage.pawco.kr/zj0s7vDbqH/{path}?quality=85&type=w&w=1200&anilimit=100"


def _powderroom_volume(product: dict) -> str:
    amount_pattern = re.compile(
        r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*(?:ml|g|kg|oz|매|pcs?|개)\b",
        re.IGNORECASE,
    )
    values: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for field, value in node.items():
                field_key = key(str(field))
                if any(token in field_key for token in ("volume", "capacity", "용량", "size", "구성")):
                    if isinstance(value, str):
                        values.append(value)
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(product)
    for value in [*values, clean(product.get("nameKr")), clean(product.get("nameEn")), clean(product.get("description"))]:
        match = amount_pattern.search(value)
        if match:
            return clean(match.group(0))
    return ""


def _powderroom_detail(client: SiteClient, product_id: int) -> dict:
    url = f"https://api.powderroom.co.kr/core/v1/common/user/product/{product_id}"
    payload = client.get(url).json()
    product = payload.get("data") or {}
    if payload.get("code") != "SUCCESS" or not product.get("id"):
        raise ValueError(f"Powderroom product detail has no product data: {product_id}")
    brand_data = product.get("brand") or {}
    secondary = product.get("secondaryCategory") or {}
    primary = secondary.get("primaryCategory") or {}
    images = product.get("images") or []
    image_path = ""
    if images:
        image = images[0].get("image") or {}
        image_path = image.get("imageUrl") or ""
    return {
        "brand": clean(brand_data.get("nameKr") or brand_data.get("nameEn") or ""),
        "name": clean(product.get("nameKr") or product.get("nameEn") or ""),
        "url": f"https://www.powderroom.co.kr/product/{product_id}",
        "price": int(float(product["price"])) if product.get("price") else None,
        "volume": _powderroom_volume(product),
        "image": _powderroom_image(image_path),
        "category": " ".join(
            item for item in (primary.get("name"), secondary.get("name")) if item
        ),
        "site": "powderroom",
    }


def _powderroom_search_products(client: SiteClient, query: str) -> list[dict]:
    search_url = "https://api.powderroom.co.kr/core/v1/common/user/search/product?" + urlencode(
        {"keyword": query}
    )
    search_payload = client.get(search_url).json()
    search_data = search_payload.get("data") or {}
    if search_payload.get("code") != "SUCCESS":
        raise ValueError("Powderroom product search did not return SUCCESS")
    product_ids = search_data.get("productIds") or []
    product_ids = [int(value) for value in product_ids if str(value).isdigit()][:10]
    if not product_ids:
        return []
    params = "&".join(
        f"productIds%5B{index}%5D={product_id}"
        for index, product_id in enumerate(product_ids)
    )
    list_url = f"https://api.powderroom.co.kr/core/v1/common/user/product?{params}"
    list_payload = client.get(list_url).json()
    list_data = list_payload.get("data") or {}
    if list_payload.get("code") != "SUCCESS":
        raise ValueError("Powderroom product list did not return SUCCESS")
    results = []
    for item in list_data.get("list") or []:
        brand_data = item.get("brand") or {}
        image_data = item.get("image") or {}
        results.append(
            {
                "product_id": int(item["id"]),
                "brand": clean(brand_data.get("nameKr") or ""),
                "name": clean(item.get("name") or ""),
                "url": f"https://www.powderroom.co.kr/product/{item['id']}",
                "price": int(float(item["price"])) if item.get("price") else None,
                "volume": "",
                "image": _powderroom_image(image_data.get("imageUrl")),
                "site": "powderroom",
            }
        )
    return results


def search_powderroom(row: dict, client: SiteClient) -> dict | None:
    """Use Powderroom's product-search API as the final identity/data fallback."""
    candidates_by_id: dict[int, dict] = {}
    for query in source_queries(row)[:2]:
        for candidate in _powderroom_search_products(client, query):
            product_id = candidate.get("product_id")
            if product_id:
                candidates_by_id.setdefault(product_id, candidate)

    ranked = sorted(
        candidates_by_id.values(),
        key=lambda candidate: (
            {"same": 0, "similar": 1, "unknown": 2, "different": 3}[
                brand_relation(row.get("brand_name"), candidate.get("brand"))
            ],
            -product_name_score(row, candidate),
        ),
    )
    best_review = None
    best_review_score = -1.0
    details = 0
    for summary in ranked:
        if hard_reject_candidate(row, summary):
            continue
        summary_score = product_name_score(row, summary)
        summary_kind_conflict = (
            product_form_conflict(row, summary)
            or not product_kinds_compatible(row.get("product_name"), summary.get("name"))
        )
        if not same_product(row, summary) and summary_score < 0.70 and not summary_kind_conflict:
            continue
        candidate = _powderroom_detail(client, summary["product_id"])
        details += 1
        if hard_reject_candidate(row, candidate):
            continue
        score = product_name_score(row, candidate)
        kind_conflict = (
            product_form_conflict(row, candidate)
            or not product_kinds_compatible(row.get("product_name"), candidate.get("name"))
        )
        volume_conflict = explicit_volume_conflict(row.get("volume"), candidate.get("volume"))
        if not same_product(row, candidate) and score < 0.70 and not kind_conflict:
            continue
        candidate["match_basis"] = (
            "product_form_conflict" if kind_conflict
            else "volume_conflict" if volume_conflict
            else "powderroom_search"
        )
        if (
            not kind_conflict
            and not volume_conflict
            and same_product(row, candidate)
            and auto_identity_confident(row, candidate)
        ):
            return candidate
        if score > best_review_score:
            best_review = candidate
            best_review_score = score
        if details >= 5:
            break
    return best_review


def hwahae_categories(client: SiteClient, product_id: int) -> list[str]:
    """Read the product taxonomy; discontinued items can have no rankings."""
    body = client.get(f"https://www.hwahae.co.kr/products/{product_id}").text
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.DOTALL)
    if not match:
        return []
    data = json.loads(match.group(1))
    product = (
        data.get("props", {})
        .get("pageProps", {})
        .get("productGoodsPairData", {})
        .get("product", {})
    )
    return extract_category_names(product)


def extract_category_names(product: dict) -> list[str]:
    """Read category labels from known product JSON shapes without using rankings."""
    found: list[str] = []

    def add_value(value) -> None:
        if isinstance(value, str):
            if clean(value):
                found.append(clean(value))
        elif isinstance(value, dict):
            label = value.get("name") or value.get("categoryName") or value.get("label")
            if isinstance(label, str) and clean(label):
                found.append(clean(label))
        elif isinstance(value, list):
            for child in value:
                add_value(child)

    def walk(node) -> None:
        if isinstance(node, dict):
            for field, value in node.items():
                normalized_field = re.sub(r"[^a-z]", "", str(field).casefold())
                if normalized_field in {
                    "categories", "category", "categoryname", "categorylabel",
                    "productcategory", "categorypath", "categorylist",
                }:
                    add_value(value)
                elif isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(product)
    return list(dict.fromkeys(found))


def search_oliveyoung(row: dict, client: SiteClient) -> dict | None:
    for query in source_queries(row):
        url = "https://m.oliveyoung.co.kr/m/search/getSearchMain.do?query=" + quote(
            query
        )
        body = client.get(url).text
        product = re.search(r"goodsNo[=:'\"\\]+(A\d{12})", body, re.IGNORECASE)
        if not product:
            continue
        goods_no = product.group(1)
        detail_url = (
            f"https://m.oliveyoung.co.kr/m/goods/getGoodsDetail.do?goodsNo={goods_no}"
        )
        detail = client.get(detail_url).text
        parser = DetailParser()
        parser.feed(detail)
        product_name = clean(unescape(parser.meta.get("og:title", "")))
        if not product_name or not same_product(row, {"name": product_name}):
            continue
        price_match = re.search(r'"(?:salePrice|price)"\s*:\s*"?(\d{3,})', detail)
        return {
            "brand": "",
            "name": product_name,
            "url": detail_url,
            "price": int(price_match.group(1)) if price_match else None,
            "volume": "",
            "image": valid_image(parser.meta.get("og:image")),
            "site": "oliveyoung",
        }
    return None


def fill(
    result: dict[str, str],
    candidate: dict | None,
    tool: bool,
    row: dict,
    basis: str = "auto_name_brand",
) -> None:
    if not candidate:
        return
    candidate_basis = candidate.get("match_basis") or basis
    current = {
        "name": result["selected_product_name"],
        "brand": result["selected_brand"],
        "url": result["selected_product_url"],
        "volume": result["volume"],
        "match_basis": result["match_basis"],
    }
    volume_conflict = explicit_volume_conflict(
        current.get("volume") or row.get("volume"), candidate.get("volume")
    )
    if volume_conflict:
        candidate_basis = "volume_conflict"
    candidate_quality = (
        2 if auto_identity_confident(row, candidate)
        else 0 if candidate_basis == "review_tag_fallback" else 1,
        product_name_score(row, candidate),
        {"same": 3, "similar": 2, "unknown": 1, "different": 0}[
            brand_relation(row.get("brand_name"), candidate.get("brand"))
        ],
    )
    current_quality = (
        2 if auto_identity_confident(row, current)
        else 0 if current["match_basis"] == "review_tag_fallback" else 1,
        product_name_score(row, current) if current["url"] else -1.0,
        {"same": 3, "similar": 2, "unknown": 1, "different": 0}[
            brand_relation(row.get("brand_name"), current.get("brand"))
        ],
    )
    compatible = (
        not current["url"]
        or same_candidate_url(current, candidate)
        or candidate_identity_compatible(current, candidate)
    ) and not volume_conflict
    replace = not current["url"] or (
        candidate_quality > current_quality and not volume_conflict
    )
    if replace and not compatible:
        for field, source_field in (
            ("price_krw", "price_source"),
            ("image_url", "image_source"),
            ("volume", "volume_source"),
        ):
            if result[source_field] != "raw_yt_product":
                result[field] = ""
                result[source_field] = ""
    if replace:
        result["selected_site"] = candidate["site"]
        result["selected_brand"] = candidate.get("brand") or ""
        result["selected_product_name"] = candidate["name"]
        result["selected_product_url"] = candidate["url"]
        result["match_basis"] = candidate_basis
    if volume_conflict or (not replace and not compatible):
        return
    for field, value in (
        ("price_krw", candidate["price"]),
        ("image_url", candidate["image"]),
        ("volume", "" if tool else candidate["volume"]),
    ):
        if value and not result[field]:
            result[field] = str(value)
            result[f"{field.split('_')[0]}_source"] = candidate["url"]


def fill_reviewed_candidate_override(
    result: dict[str, str], override: dict[str, str]
) -> None:
    result["selected_site"] = override["selected_site"]
    result["selected_brand"] = override["selected_brand"]
    result["selected_product_name"] = override["selected_product_name"]
    result["selected_product_url"] = override["selected_product_url"]
    result["match_basis"] = "reviewed_override"
    for field, source_field in (
        ("price_krw", "price_source"),
        ("volume", "volume_source"),
        ("image_url", "image_source"),
    ):
        # Keep current trustworthy raw values. Otherwise use the value and
        # provenance already checked in the user's reviewed report.
        if result[source_field] == "raw_yt_product":
            continue
        if override[field]:
            result[field] = override[field]
            result[source_field] = override[source_field]


def collect_one(
    row: dict,
    glowpick: GlowpickClient,
    hwahae: SiteClient,
    oliveyoung: SiteClient,
    powderroom: SiteClient,
) -> dict[str, str]:
    tool = is_tool(row)
    output = {field: "" for field in FIELDS}
    output.update(
        {
            "yt_product_id": row["yt_product_id"],
            "source_brand": row["brand_name"],
            "source_product_name": row["product_name"],
            "source_option_name": row["option_name"]
            or REVIEWED_PRODUCT_OPTIONS_BY_ID.get(row["yt_product_id"], ""),
            "source_category": row["category"] or "",
            "is_tool": "yes" if tool else "no",
            "tags": json.dumps(["youtube", category_tag(row)], ensure_ascii=False),
        }
    )
    reviewed_not_found_reason = REVIEWED_NOT_FOUND_BY_ID.get(row["yt_product_id"])
    if reviewed_not_found_reason:
        output["lookup_status"] = "not_found"
        output["review_reason"] = reviewed_not_found_reason
        return output
    # Existing reliable values remain in the raw table; collect only missing fields.
    if row["price_krw"] and "추정" not in (row["price_type"] or ""):
        output["price_krw"] = str(row["price_krw"])
        output["price_source"] = "raw_yt_product"
    if row["image_url"]:
        output["image_url"] = row["image_url"]
        output["image_source"] = "raw_yt_product"
    if (
        row["volume"]
        and not tool
        and row["volume"].strip() not in {"1g / 8g", "N", "-"}
        and not (
            row["yt_product_id"] == "yt-351934dd91efb5abaa52"
            and row["volume"].strip() == "15g / 30ml"
        )
    ):
        output["volume"] = row["volume"]
        output["volume_source"] = "raw_yt_product"
    errors = []
    review_fallback = None
    powderroom_category = ""
    reviewed_candidate = REVIEWED_CANDIDATE_OVERRIDES_BY_ID.get(row["yt_product_id"])
    reviewed_product_id = REVIEWED_PRODUCT_IDS.get(row["yt_product_id"])
    reviewed_hwahae = REVIEWED_HWAHAE_IDS.get(row["yt_product_id"])
    reviewed_hwahae_found = False
    if reviewed_candidate is not None:
        fill_reviewed_candidate_override(output, reviewed_candidate)
    elif reviewed_product_id is not None:
        try:
            fill(
                output,
                glowpick_detail(glowpick, reviewed_product_id, ""),
                tool,
                row,
                basis="reviewed_override",
            )
        except RateLimitStopped:
            raise
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"reviewed Glowpick URL: {type(exc).__name__}: {exc}")
    elif reviewed_hwahae is not None:
        try:
            candidate = reviewed_hwahae_detail(hwahae, *reviewed_hwahae)
            if candidate:
                fill(output, candidate, tool, row, basis="reviewed_override")
                reviewed_hwahae_found = True
        except (Blocked, RateLimitStopped):
            raise
        except (
            httpx.HTTPError, requests.RequestException, ValueError,
            KeyError, json.JSONDecodeError,
        ) as exc:
            errors.append(f"reviewed Hwahae URL: {type(exc).__name__}: {exc}")
    sites = [] if (
        reviewed_candidate is not None or reviewed_product_id is not None or reviewed_hwahae_found
    ) else (
        [("oliveyoung", oliveyoung)] if tool else []
    )
    if reviewed_candidate is None and reviewed_product_id is None and not reviewed_hwahae_found:
        sites += [("glowpick", glowpick), ("hwahae", hwahae), ("powderroom", powderroom)]
    for name, client in sites:
        if (
            output["price_krw"] and output["image_url"] and (tool or output["volume"])
            and category_tag(row) != "unknown"
            and output["selected_product_url"]
            and output["match_basis"] != "unknown_brand_ambiguous"
            and auto_identity_confident(
                row,
                {"name": output["selected_product_name"], "brand": output["selected_brand"]},
            )
        ):
            break
        try:
            candidate = {
                "oliveyoung": search_oliveyoung,
                "glowpick": search_glowpick,
                "hwahae": search_hwahae,
                "powderroom": search_powderroom,
            }[name](row, client)
            if (
                name == "glowpick"
                and candidate
                and candidate.get("match_basis") == "review_tag_fallback"
            ):
                review_fallback = candidate
            else:
                fill(output, candidate, tool, row)
                if (
                    name == "powderroom"
                    and candidate
                    and output["selected_site"] == "powderroom"
                    and output["selected_product_url"] == candidate.get("url")
                ):
                    powderroom_category = candidate.get("category") or ""
        except OptionalSourceBlocked as exc:
            errors.append(str(exc))
        except (Blocked, RateLimitStopped):
            raise
        except (
            httpx.HTTPError,
            requests.RequestException,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    if not output["selected_product_url"] and review_fallback:
        fill(output, review_fallback, tool, row, basis="review_tag_fallback")
    reviewed_price = REVIEWED_PRICE_OVERRIDES_BY_ID.get(row["yt_product_id"])
    if reviewed_price:
        output["price_krw"] = str(reviewed_price[0])
        output["price_source"] = reviewed_price[1]
    category = category_tag(row)
    if category == "unknown" and output["selected_site"] == "glowpick":
        product_match = re.search(r"/products/(\d+)", output["selected_product_url"])
        if product_match:
            try:
                categories = glowpick_categories(glowpick, int(product_match.group(1)))
                category = category_tag(
                    row,
                    " ".join([*categories, output["selected_product_name"]]),
                )
            except RateLimitStopped:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"글로우픽 카테고리 조회: {type(exc).__name__}: {exc}")
    if category == "unknown" and output["selected_site"] == "hwahae":
        product_match = re.search(r"/products/(\d+)", output["selected_product_url"])
        if product_match:
            try:
                categories = hwahae_categories(hwahae, int(product_match.group(1)))
                category = category_tag(row, " ".join(categories))
            except (Blocked, RateLimitStopped):
                raise
            except (httpx.HTTPError, requests.RequestException, ValueError) as exc:
                errors.append(f"화해 카테고리 조회: {type(exc).__name__}: {exc}")
    if category == "unknown" and output["selected_site"] == "powderroom":
        category = category_tag(row, powderroom_category)
    if category == "unknown":
        category = category_tag(row, output["selected_product_name"])
    if category != "unknown":
        output["tags"] = json.dumps(["youtube", category], ensure_ascii=False)
    missing = [
        name
        for name in ("price_krw", "image_url", *([] if tool else ["volume"]))
        if not output[name]
    ]
    review = []
    if not output["selected_product_url"]:
        review.append(
            "검색 중 기술 오류로 후보 확인 불가" if errors else "검색 결과에서 후보를 찾지 못함"
        )
    if output["selected_product_url"] and category == "unknown":
        review.append("카테고리 미확인")
    if (
        output["selected_product_url"]
        and reviewed_product_id is None
        and reviewed_candidate is None
        and not reviewed_hwahae_found
    ):
        selected_candidate = {
            "name": output["selected_product_name"],
            "brand": output["selected_brand"],
            "url": output["selected_product_url"],
        }
        identity_override = reviewed_identity_matches(row, selected_candidate)
        if identity_override:
            output["match_basis"] = "reviewed_identity_override"
        else:
            if output["match_basis"] == "review_tag_fallback":
                review.append("글로우픽 리뷰 태그 후보로 확인 필요")
            if output["match_basis"] == "unknown_brand_ambiguous":
                review.append("동일 제품명에 서로 다른 브랜드 후보가 있음")
            if output["match_basis"] == "product_form_conflict" or product_form_conflict(
                row, selected_candidate
            ):
                review.append("상품 종류가 후보와 달라 확인 필요")
            if output["match_basis"] == "volume_conflict":
                review.append("패키지 용량이 달라 확인 필요")
            if known_brand(row["brand_name"]) and not output["selected_brand"]:
                review.append("검색 후보 브랜드 정보 없음")
            if explicit_option_conflict(row, selected_candidate):
                review.append("옵션 표기가 후보와 달라 확인 필요")
            if (
                not auto_identity_confident(row, selected_candidate)
                or key(row["product_name"]) == key(row["option_name"])
            ):
                review.append("제품명 근거 확인 필요")
            selected_brand_relation = brand_relation(row["brand_name"], output["selected_brand"])
            brand_was_explicit_in_title = brand_candidate_allowed(row, selected_candidate)
            if selected_brand_relation == "similar" and not brand_was_explicit_in_title:
                review.append("브랜드 표기 유사 후보 확인 필요")
            elif selected_brand_relation == "different" and not brand_was_explicit_in_title:
                review.append("브랜드 표기 차이 확인 필요")
    if missing:
        missing_labels = {
            "price_krw": "가격",
            "image_url": "이미지",
            "volume": "용량",
        }
        review.append(
            "미수집 정보: " + ", ".join(missing_labels[field] for field in missing)
        )
    identity_review = [reason for reason in review if not reason.startswith("미수집 정보:")]
    if not output["selected_product_url"]:
        output["lookup_status"] = "errors" if errors else "not_found"
    elif identity_review:
        output["lookup_status"] = "needs_review"
    elif missing:
        output["lookup_status"] = "incomplete_data"
    else:
        output["lookup_status"] = "complete"
    output["review_reason"] = "; ".join(review)
    output["error"] = "; ".join(errors + (["missing: " + ",".join(missing)] if missing else []))[
        :500
    ]
    return output


def read_csv(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Unexpected report columns: {path}")
        rows = list(reader)
    if len({row["yt_product_id"] for row in rows}) != len(rows):
        raise ValueError(f"Duplicate product IDs in report: {path}")
    return {row["yt_product_id"]: row for row in rows}


def save(path: Path, rows: dict[str, dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda row: row["yt_product_id"]))
    try:
        os.replace(temp, path)
        return path
    except PermissionError:
        recovery = path.with_name(f"{path.stem}.recovery-{time.time_ns()}{path.suffix}")
        os.replace(temp, recovery)
        print(f"CSV 파일이 잠겨 복구 파일로 저장함: {recovery}", flush=True)
        return recovery


def missing_required_fields(row: dict[str, str]) -> list[str]:
    tool = row.get("is_tool") == "yes" or '"tool"' in (row.get("tags") or "")
    required = ["price_krw", "image_url"] + ([] if tool else ["volume"])
    return [field for field in required if not (row.get(field) or "").strip()]


def is_retryable_result(row: dict[str, str]) -> bool:
    error = row.get("error") or ""
    transient_failure = bool(
        re.search(
            r"(?:HTTPStatusError: Server error|HTTP 5\d\d|\b5\d\d Internal Server Error|"
            r"ConnectTimeout|ReadTimeout|WriteTimeout|PoolTimeout|ConnectError|"
            r"RemoteProtocolError|Connection reset|ConnectionError)",
            error,
            re.IGNORECASE,
        )
    )
    unresolved_identity_or_data = (
        bool(missing_required_fields(row))
        or not (row.get("selected_product_url") or "").strip()
        or '"unknown"' in (row.get("tags") or "")
    )
    return transient_failure and unresolved_identity_or_data


def merge_retry_result(previous: dict[str, str], retried: dict[str, str]) -> dict[str, str]:
    """Retain previous fields only for the same product or untouched raw values."""
    previous_url = previous.get("selected_product_url") or ""
    retried_url = retried.get("selected_product_url") or ""
    merged = dict(previous if previous_url and not retried_url else retried)
    identity_fields = (
        "selected_site",
        "selected_brand",
        "selected_product_name",
        "selected_product_url",
        "match_basis",
    )
    if not merged.get("selected_product_url"):
        for field in identity_fields:
            merged[field] = previous.get(field, "")
    for field, source_field in (
        ("price_krw", "price_source"),
        ("volume", "volume_source"),
        ("image_url", "image_source"),
    ):
        same_identity = previous_url == (merged.get("selected_product_url") or "")
        trusted_raw = previous.get(source_field) == "raw_yt_product"
        if not merged.get(field) and previous.get(field) and (same_identity or trusted_raw):
            merged[field] = previous[field]
            merged[source_field] = previous.get(source_field, "")
    if (
        previous_url == (merged.get("selected_product_url") or "")
        and '"unknown"' in (merged.get("tags") or "")
        and '"unknown"' not in (previous.get("tags") or "")
    ):
        merged["tags"] = previous["tags"]

    has_candidate = bool(merged.get("selected_product_url"))
    reason_source = retried if retried_url else previous
    identity_reasons = [
        reason.strip()
        for reason in (reason_source.get("review_reason") or "").split(";")
        if reason.strip() and not reason.strip().startswith("미수집 정보:")
    ]
    technical_errors = [
        error
        for error in (retried.get("error") or "").split("; ")
        if error and not error.startswith("missing:")
    ]
    if not has_candidate:
        identity_reasons = [
            "검색 중 기술 오류로 후보 확인 불가"
            if technical_errors
            else "검색 결과에서 후보를 찾지 못함"
        ]
    missing = missing_required_fields(merged)
    if missing:
        labels = {"price_krw": "가격", "image_url": "이미지", "volume": "용량"}
        identity_reasons.append("미수집 정보: " + ", ".join(labels[field] for field in missing))
    merged["review_reason"] = "; ".join(dict.fromkeys(identity_reasons))
    if not has_candidate:
        merged["lookup_status"] = "errors" if technical_errors else "not_found"
    elif any(not reason.startswith("미수집 정보:") for reason in identity_reasons):
        merged["lookup_status"] = "needs_review"
    elif missing:
        merged["lookup_status"] = "incomplete_data"
    else:
        merged["lookup_status"] = "complete"

    errors = list(technical_errors)
    if missing:
        errors.append("missing:" + ",".join(missing))
    merged["error"] = "; ".join(errors)[:500]
    return merged


async def source_rows(args: argparse.Namespace) -> list[dict]:
    with EXCLUSIONS.open(encoding="utf-8-sig", newline="") as handle:
        excluded = {row["yt_product_id"] for row in csv.DictReader(handle)}
    password = (
        getattr(args, "password", None)
        or os.environ.get("POSTGRES_PASSWORD")
        or getpass.getpass("Local PostgreSQL password: ")
    )
    args.password = password
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=args.port,
        database=args.database,
        user="vishue",
        password=password,
        ssl=False,
    )
    try:
        async with conn.transaction(readonly=True):
            fetched = await conn.fetch("""SELECT y.yt_product_id, y.brand_name, y.product_name,
                       y.option_name, y.category, y.makeup_zone, y.price_krw, y.price_type,
                       y.volume, y.image_url
                 FROM public.raw_yt_product y
                 WHERE EXISTS (SELECT 1 FROM public.raw_yt_product_mention mn
                               WHERE mn.yt_product_id = y.yt_product_id)
                   AND NOT EXISTS (SELECT 1 FROM public.yt_oy_product_match m
                                   WHERE m.yt_product_id=y.yt_product_id
                                     AND m.decision_status='confirmed')
                   AND NOT EXISTS (SELECT 1 FROM public.yt_catalog_product_link l
                                   WHERE l.source_yt_product_id=y.yt_product_id)
                   AND NOT EXISTS (SELECT 1 FROM public.products p WHERE p.id=y.yt_product_id)
                 ORDER BY y.yt_product_id""")
    finally:
        await conn.close()
    return [dict(row) for row in fetched if row["yt_product_id"] not in excluded]


async def apply_report(args: argparse.Namespace) -> None:
    sources = {row["yt_product_id"]: row for row in await source_rows(args)}
    report = read_csv(args.report)
    skipped_review = 0
    skipped_incomplete = 0
    skipped_not_found = 0
    skipped_errors = 0
    planned = []
    for product_id, row in report.items():
        source = sources.get(product_id)
        if source is None:
            raise ValueError(f"Report product is no longer eligible: {product_id}")
        if (
            row["source_brand"],
            row["source_product_name"],
            row["source_option_name"],
        ) != (
            source["brand_name"],
            source["product_name"],
            source["option_name"] or REVIEWED_PRODUCT_OPTIONS_BY_ID.get(product_id, ""),
        ):
            raise ValueError(f"Source identity changed: {product_id}")
        try:
            tags = json.loads(row["tags"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid source category: {product_id}") from exc
        source_category = category_tag(source)
        if (
            not isinstance(tags, list)
            or len(tags) != 2
            or tags[0] != "youtube"
            or tags[1] not in {
                "tool", "suncare", "lip", "cheek", "base", "eye", "skincare", "unknown"
            }
            or (source_category != "unknown" and tags[1] != source_category)
        ):
            raise ValueError(f"Source category changed: {product_id}")
        reviewed_product_id = REVIEWED_PRODUCT_IDS.get(product_id)
        reviewed_candidate = REVIEWED_CANDIDATE_OVERRIDES_BY_ID.get(product_id)
        reviewed_hwahae = REVIEWED_HWAHAE_IDS.get(product_id)
        if row["match_basis"] == "reviewed_override":
            expected_reviewed_url = (
                reviewed_candidate["selected_product_url"]
                if reviewed_candidate
                else f"https://www.glowpick.com/products/{reviewed_product_id}"
                if reviewed_product_id is not None
                else f"https://www.hwahae.co.kr/products/{reviewed_hwahae[0]}"
                if reviewed_hwahae is not None
                else ""
            )
            if row["selected_product_url"] != expected_reviewed_url:
                raise ValueError(f"Reviewed product URL changed: {product_id}")
        if row["lookup_status"] != "complete":
            if row["lookup_status"] == "needs_review":
                skipped_review += 1
            elif row["lookup_status"] == "incomplete_data":
                skipped_incomplete += 1
            elif row["lookup_status"] == "not_found":
                skipped_not_found += 1
            else:
                skipped_errors += 1
                continue
            continue
        if not row["selected_product_url"]:
            raise ValueError(f"Complete row has no identified product: {product_id}")
        if row["match_basis"] == "unknown_brand_ambiguous":
            raise ValueError(f"Complete row has conflicting product brands: {product_id}")
        if (
            reviewed_product_id is None
            and reviewed_candidate is None
            and reviewed_hwahae is None
            and not auto_identity_confident(
            source,
            {"name": row["selected_product_name"], "brand": row["selected_brand"]},
            )
        ):
            raise ValueError(f"Complete row lacks product identity evidence: {product_id}")
        price = int(row["price_krw"]) if row["price_krw"] else None
        if price is not None and price <= 0:
            raise ValueError(f"Invalid price: {product_id}")
        image = valid_image(row["image_url"])
        if row["image_url"] and not image:
            raise ValueError(f"Invalid image URL: {product_id}")
        price_source = row["price_source"]
        image_source = row["image_source"]
        volume_source = row["volume_source"]
        if any(
            value and not value.startswith("https://") and value != "raw_yt_product"
            for value in (price_source, image_source, volume_source)
        ):
            raise ValueError(f"Invalid evidence URL: {product_id}")
        update_price = bool(
            price
            and price_source != "raw_yt_product"
            and (not source["price_krw"] or "추정" in (source["price_type"] or ""))
        )
        update_image = bool(
            image and image_source != "raw_yt_product" and not source["image_url"]
        )
        update_volume = bool(
            not is_tool(source)
            and row["volume"]
            and volume_source != "raw_yt_product"
            and (
                not source["volume"]
                or source["volume"].strip() in {"1g / 8g", "N", "-"}
            )
        )
        if update_price or update_image or update_volume:
            planned.append(
                (
                    product_id,
                    price if update_price else None,
                    image if update_image else None,
                    image_source if update_image else None,
                    row["volume"] if update_volume else None,
                )
            )
    print(
        f"Report rows: {len(report):,}; eligible source rows: {len(sources):,}; "
        f"identity review rows skipped: {skipped_review:,}; "
        f"incomplete data rows skipped: {skipped_incomplete:,}; "
        f"not found rows skipped: {skipped_not_found:,}; technical error rows skipped: {skipped_errors:,}; "
        f"source rows to update: {len(planned):,}"
    )
    if args.phase == "preflight":
        print("Preflight passed; no database rows were written")
        return
    if not planned:
        return
    password = args.password
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=args.port,
        database=args.database,
        user="vishue",
        password=password,
        ssl=False,
    )
    try:
        async with conn.transaction():
            for product_id, price, image, image_source, volume in planned:
                await conn.execute(
                    """UPDATE public.raw_yt_product
                      SET price_krw=COALESCE($2,price_krw),
                          price_type=CASE WHEN $2::integer IS NOT NULL
                                          THEN '보강 정가' ELSE price_type END,
                          image_url=COALESCE($3,image_url),
                          image_source_url=CASE WHEN $3::text IS NOT NULL
                              THEN $4 ELSE image_source_url END,
                          volume=COALESCE($5,volume), updated_at=now()
                      WHERE yt_product_id=$1""",
                    product_id,
                    price,
                    image,
                    image_source,
                    volume,
                )
    finally:
        await conn.close()
    print(
        f"Committed {len(planned):,} source product updates; serving tags remain in report CSV"
    )


def run(args: argparse.Namespace) -> None:
    if args.phase != "collect":
        asyncio.run(apply_report(args))
        return
    rows = asyncio.run(source_rows(args))
    previous = read_csv(args.report)
    if args.refresh:
        previous = {}
    sources_by_id = {row["yt_product_id"]: row for row in rows}
    stale_complete_ids = {
        product_id
        for product_id, result in previous.items()
        if product_id in sources_by_id
        and result.get("lookup_status") == "complete"
        and product_id not in REVIEWED_PRODUCT_IDS
        and product_id not in REVIEWED_CANDIDATE_OVERRIDES_BY_ID
        and product_id not in REVIEWED_HWAHAE_IDS
        and not auto_identity_confident(
            sources_by_id[product_id],
            {"name": result.get("selected_product_name"),
             "brand": result.get("selected_brand")},
        )
    }
    retry_ids = {
        product_id
        for product_id, result in previous.items()
        if args.retry_errors
        and result.get("lookup_status") not in {"not_found"}
        and (
            result.get("lookup_status") in {"errors", "error"}
            or is_retryable_result(result)
        )
    }
    retry_ids.update(stale_complete_ids)
    requested_reprocess_ids = set(args.reprocess_ids)
    unknown_reprocess_ids = requested_reprocess_ids - set(sources_by_id)
    if unknown_reprocess_ids:
        raise ValueError(
            "Requested reprocess IDs were not found in raw_yt_product: "
            + ", ".join(sorted(unknown_reprocess_ids))
        )
    retry_ids.update(requested_reprocess_ids)
    pending = [
        row
        for row in rows
        if row["yt_product_id"] not in previous or row["yt_product_id"] in retry_ids
    ]
    if args.limit:
        pending = pending[: args.limit]
    print(
        f"Eligible {len(rows):,}; already collected {len(previous):,}; pending {len(pending):,}; "
        f"retrying {len(retry_ids):,} rows (unsafe prior complete "
        f"{len(stale_complete_ids):,}); workers {args.workers}",
        flush=True,
    )
    glowpick = GlowpickClient(args.delay)
    hwahae = SiteClient("Hwahae", args.delay)
    oliveyoung = SiteClient("Olive Young", args.delay)
    powderroom = SiteClient("Powderroom", args.delay)
    interrupted = False
    pool = ThreadPoolExecutor(max_workers=args.workers)
    processed_ids: set[str] = set()

    def collect_batch(batch: list[dict], label: str, retry_merge: bool = False) -> None:
        futures = {
            pool.submit(collect_one, row, glowpick, hwahae, oliveyoung, powderroom): row
            for row in batch
        }
        for finished, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            product_id = source["yt_product_id"]
            try:
                result = future.result()
            except (Blocked, RateLimitStopped):
                glowpick.stop()
                hwahae.stop()
                oliveyoung.stop()
                powderroom.stop()
                for item in futures:
                    item.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - preserve the batch checkpoint
                result = {field: "" for field in FIELDS}
                result.update(
                    {
                        "yt_product_id": product_id,
                        "source_brand": source["brand_name"],
                        "source_product_name": source["product_name"],
                        "source_option_name": source["option_name"] or "",
                        "source_category": source["category"] or "",
                        "is_tool": "yes" if is_tool(source) else "no",
                        "tags": json.dumps(["youtube", category_tag(source)], ensure_ascii=False),
                        "lookup_status": "errors",
                        "error": str(exc)[:500],
                    }
                )
            if retry_merge and product_id in previous:
                result = merge_retry_result(previous[product_id], result)
            previous[product_id] = result
            processed_ids.add(product_id)
            if finished % 10 == 0 or finished == len(batch):
                args.report = save(args.report, previous)
                counts = Counter(item["lookup_status"] for item in previous.values())
                print(
                    f"{label} {finished}/{len(batch)} (complete {counts['complete']}; "
                    f"needs_review {counts['needs_review']}; "
                    f"incomplete_data {counts['incomplete_data']}; "
                    f"not_found {counts['not_found']}; "
                    f"errors {counts['errors'] + counts['error']})",
                    flush=True,
                )

    try:
        if pending:
            collect_batch(pending, "Enrich")
        retry_batch = [
            row
            for row in rows
            if row["yt_product_id"] in previous
            and (not args.limit or row["yt_product_id"] in processed_ids)
            and is_retryable_result(previous[row["yt_product_id"]])
        ]
        if retry_batch:
            print(
                f"Post-run retry: {len(retry_batch)} rows with transient technical errors; "
                "one additional attempt",
                flush=True,
            )
            collect_batch(retry_batch, "Retry after 5xx", retry_merge=True)
    except KeyboardInterrupt:
        interrupted = True
        glowpick.stop()
        hwahae.stop()
        oliveyoung.stop()
        powderroom.stop()
        print("중단 요청을 받음; 진행한 수집 결과를 저장하는 중", flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if previous:
            args.report = save(args.report, previous)
        glowpick.close()
        hwahae.close()
        oliveyoung.close()
        powderroom.close()
    if interrupted:
        print(f"중단 완료; 저장된 결과: {args.report}", flush=True)
        return
    print(f"Review CSV: {args.report}; no database rows were written")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{__doc__} Version {SCRIPT_VERSION}.")
    parser.add_argument(
        "--phase", choices=("collect", "preflight", "apply"), default="collect"
    )
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--reprocess-ids",
        nargs="*",
        default=[],
        help="Recollect only the specified source IDs even if the report already contains them.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry only previously technical-error rows; no-result rows remain skipped.",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 10 or args.delay < 0 or args.limit < 0:
        parser.error("workers must be 1..10; delay and limit must be nonnegative")
    print(f"Catalog enrichment script v{SCRIPT_VERSION}", flush=True)
    run(args)


if __name__ == "__main__":
    main()
