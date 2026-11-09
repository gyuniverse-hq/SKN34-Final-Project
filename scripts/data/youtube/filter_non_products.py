"""Classify obvious non-product YouTube rows and prepare a manual review CSV.

This script reads the local database only. It never writes to PostgreSQL. The
apply phase updates only the reviewed non_product_exclusions.csv manifest.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import re
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
DEFAULT_EXCLUSIONS = HERE / "non_product_exclusions.csv"
DEFAULT_REVIEW = Path.home() / "Downloads" / "youtube-non-product-review.csv"
DEFAULT_AUTO_REPORT = Path.home() / "Downloads" / "youtube-non-product-auto-exclusions.csv"
EXCLUSION_FIELDS = ("yt_product_id", "brand_name", "product_name", "exclusion_reason")
REVIEW_FIELDS = (
    "decision",
    "yt_product_id",
    "brand_name",
    "product_name",
    "option_name",
    "category",
    "makeup_zone",
    "price_krw",
    "price_type",
    "review_reason",
)
AUTO_PHRASES = (
    ("ㅠㅠ", "상품명이 감정 반응 문장임"),
    ("왜 단종", "상품명이 단종에 대한 반응 문장임"),
    ("제 최애", "상품명이 개인 감상 문장임"),
    ("대체 가능합니다", "상품명이 대체 방법 설명 문장임"),
    ("생각", "상품명이 개인 의견·사용감 설명 문장임"),
    ("것 같", "상품명이 추측·설명 문장임"),
    ("느낌", "상품명이 감상·설명 문장임"),
    ("같아요", "상품명이 추측·설명 문장임"),
    ("제품", "상품명이 제품을 특정하지 않는 설명 문장임"),
    ("직접", "상품명이 직접 구매·제작을 나타내며 상품을 특정하지 않음"),
    ("..", "상품명에 연속 마침표가 포함된 설명 문장임"),
)
UNKNOWN_BRANDS = {"", "확인 필요", "확인필요", "미확인", "unknown"}


def normalize(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def auto_exclusion_reason(row: asyncpg.Record) -> str | None:
    brand = normalize(row["brand_name"])
    name = (row["product_name"] or "").strip()
    if "렌즈" in brand or "렌즈" in name:
        return "브랜드명 또는 상품명에 렌즈가 포함된 비화장품 항목"

    for phrase, reason in AUTO_PHRASES:
        if phrase in name:
            return reason

    return None


def review_reason(row: asyncpg.Record) -> str:
    name = (row["product_name"] or "").strip()
    brand = normalize(row["brand_name"])
    if brand in UNKNOWN_BRANDS and re.search(
        r"분들에게|분들도|발라보|개인적으로|컬러입니다|가성비|구매처|\d[,.]?\d*\s*원",
        name,
    ):
        return "브랜드 미확인 상태에서 상품명이 설명·사용감·가격 문장처럼 보임"
    if name and brand and normalize(name) == brand:
        return "상품명이 브랜드명과 같아 개별 제품을 특정하기 어려움"
    if re.search(r"[/／]|\s+and\s+|\s+및\s+", name, re.IGNORECASE):
        return "상품명에 복수 제품이 함께 기록되었을 가능성"
    return "상품 식별 가능성 확인 필요"


def read_exclusions(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXCLUSION_FIELDS:
            raise ValueError(f"Exclusion CSV columns must be {EXCLUSION_FIELDS}")
        rows = list(reader)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        product_id = row["yt_product_id"].strip()
        if not product_id or product_id in result:
            raise ValueError(f"Missing or duplicate exclusion ID: {product_id}")
        if not row["exclusion_reason"].strip():
            raise ValueError(f"Missing exclusion reason: {product_id}")
        result[product_id] = {key: value or "" for key, value in row.items()}
    return result


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def read_review_decisions(path: Path, review_ids: set[str]) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(REVIEW_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Review CSV must include columns: {REVIEW_FIELDS}")
        rows = list(reader)
    decisions: dict[str, str] = {}
    for row in rows:
        product_id = row["yt_product_id"].strip()
        decision = (row["decision"] or "").strip().casefold()
        if product_id not in review_ids:
            raise ValueError(f"Review decision is not from the latest report: {product_id}")
        if decision not in {"", "keep", "exclude"}:
            raise ValueError(f"Decision must be blank, keep, or exclude: {product_id}")
        if product_id in decisions:
            raise ValueError(f"Duplicate review decision: {product_id}")
        decisions[product_id] = decision
    return decisions


async def run(args: argparse.Namespace) -> None:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only a local PostgreSQL host is supported")
    exclusions = read_exclusions(args.exclusions)
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        database=args.database,
        ssl=False,
        server_settings={"application_name": "yt_non_product_filter_read_only"},
    )
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(
                """SELECT y.yt_product_id, y.brand_name, y.product_name,
                          y.option_name, y.category, y.makeup_zone, y.price_krw,
                          y.price_type,
                          EXISTS (SELECT 1 FROM public.yt_oy_product_match m
                                  WHERE m.yt_product_id = y.yt_product_id
                                    AND m.decision_status = 'confirmed') AS matched_oy,
                          EXISTS (SELECT 1 FROM public.yt_catalog_product_link l
                                  WHERE l.source_yt_product_id = y.yt_product_id) AS linked_catalog,
                          EXISTS (SELECT 1 FROM public.products p
                                  WHERE p.id = y.yt_product_id) AS in_products
                   FROM public.raw_yt_product y
                   ORDER BY y.yt_product_id"""
            )
    finally:
        await conn.close()

    by_id = {row["yt_product_id"]: row for row in rows}
    for product_id, exclusion in exclusions.items():
        raw = by_id.get(product_id)
        if raw is None:
            raise ValueError(f"Exclusion ID is absent from raw_yt_product: {product_id}")
        if (raw["brand_name"] or "", raw["product_name"] or "") != (
            exclusion["brand_name"],
            exclusion["product_name"],
        ):
            raise ValueError(f"Exclusion identity changed in the source DB: {product_id}")

    candidates = [
        row
        for row in rows
        if not row["matched_oy"] and not row["linked_catalog"] and not row["in_products"]
    ]
    auto_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    for row in candidates:
        reason = auto_exclusion_reason(row)
        if reason and row["yt_product_id"] not in exclusions:
            auto_rows.append(
                {
                    "yt_product_id": row["yt_product_id"],
                    "brand_name": row["brand_name"] or "",
                    "product_name": row["product_name"] or "",
                    "exclusion_reason": reason,
                }
            )
        elif not reason and row["yt_product_id"] not in exclusions:
            review_rows.append(
                {
                    "decision": "",
                    **{
                        field: "" if row[field] is None else str(row[field])
                        for field in REVIEW_FIELDS
                        if field not in {"decision", "review_reason"}
                    },
                    "review_reason": review_reason(row),
                }
            )

    if args.phase == "preview":
        write_csv(args.review, REVIEW_FIELDS, review_rows)
        write_csv(args.auto_report, EXCLUSION_FIELDS, auto_rows)
        print(
            f"Unmatched, unlinked source products: {len(candidates):,}; "
            f"new auto-exclusion candidates: {len(auto_rows):,}; "
            f"manual review rows: {len(review_rows):,}; "
            f"already excluded: {len(exclusions):,}"
        )
        print(f"Auto-exclusion report: {args.auto_report}")
        print(f"Review CSV: {args.review}")
        print("Preview complete; database and exclusion manifest were not changed")
        return

    decisions: dict[str, str] = {}
    if args.review_decisions:
        decisions = read_review_decisions(
            args.review_decisions, {row["yt_product_id"] for row in review_rows}
        )
    additions = {row["yt_product_id"]: row for row in auto_rows}
    for row in review_rows:
        product_id = row["yt_product_id"]
        if decisions.get(product_id) == "exclude":
            additions[product_id] = {
                "yt_product_id": product_id,
                "brand_name": row["brand_name"],
                "product_name": row["product_name"],
                "exclusion_reason": f"수동 검수 제외: {row['review_reason']}",
            }
    merged = dict(exclusions)
    merged.update(additions)
    output_rows = sorted(merged.values(), key=lambda item: item["yt_product_id"])
    write_csv(args.exclusions, EXCLUSION_FIELDS, output_rows)
    print(
        f"Added {len(additions):,} exclusions ({len(auto_rows):,} automatic, "
        f"{sum(value == 'exclude' for value in decisions.values()):,} reviewed); "
        f"manifest total {len(output_rows):,}; database was not changed"
    )
    print(f"Updated exclusion CSV: {args.exclusions}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preview", "apply"), default="preview")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--auto-report", type=Path, default=DEFAULT_AUTO_REPORT)
    parser.add_argument("--review-decisions", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
