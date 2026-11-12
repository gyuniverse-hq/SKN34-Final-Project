"""Preview YouTube-to-Olive Young product candidates without automatic confirmation.

Brand aliases are accepted only from a reviewer-approved CSV. The default run writes
review reports and never changes the database. --apply stores candidate rows; a person
must still confirm the product and, where applicable, the exact option.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import re
import unicodedata
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import asyncpg

RULE_VERSION = "v1"
UNKNOWN_BRANDS = {"확인 필요", "확인필요", "미확인", "unknown"}
ALIAS_COLUMNS = ("yt_brand", "oy_brand", "reviewed_by", "reviewed_at")
CANDIDATE_COLUMNS = (
    "yt_product_id",
    "yt_brand",
    "yt_product_name",
    "yt_option_name",
    "oy_goods_no",
    "oy_brand",
    "oy_goods_name",
    "oy_option_id",
    "oy_option_name",
    "candidate_rank",
    "product_score",
    "option_score",
    "match_method",
    "match_reason",
)
BRAND_COLUMNS = ("yt_brand", "yt_products", "oy_brand_suggestions")
UNMATCHED_COLUMNS = (
    "yt_product_id",
    "yt_brand",
    "yt_product_name",
    "yt_option_name",
    "product_url",
    "image_url",
    "reason",
)


def key(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def loose_key(value: str | None) -> str:
    return re.sub(r"[^\w가-힣]", "", key(value))


def ratio(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, loose_key(left), loose_key(right)).ratio()


def product_ratio(yt_name: str, oy_name: str, yt_brand: str, oy_brand: str) -> float:
    """Compare both the recorded names and names without a repeated brand prefix."""
    raw_score = ratio(yt_name, oy_name)

    def core(name: str, brand: str) -> str:
        without_promo = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", name).strip()
        normalized = loose_key(without_promo)
        brand_prefix = loose_key(brand)
        if brand_prefix and normalized.startswith(brand_prefix):
            normalized = normalized[len(brand_prefix) :]
        return normalized

    yt_core = core(yt_name, yt_brand)
    oy_core = core(oy_name, oy_brand)
    if not yt_core or not oy_core:
        return raw_score
    return max(raw_score, SequenceMatcher(None, yt_core, oy_core).ratio())


def load_aliases(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"Brand alias file is missing: {path}")
    aliases: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ALIAS_COLUMNS:
            raise ValueError(f"Brand alias columns must be {ALIAS_COLUMNS}")
        for line, row in enumerate(reader, 2):
            yt_brand = key(row["yt_brand"])
            oy_brand = key(row["oy_brand"])
            if not all((yt_brand, oy_brand, row["reviewed_by"], row["reviewed_at"])):
                raise ValueError(f"Incomplete reviewed brand alias at line {line}")
            date.fromisoformat(row["reviewed_at"])
            if yt_brand in aliases:
                raise ValueError(f"Duplicate YouTube brand alias at line {line}")
            aliases[yt_brand] = oy_brand
    return aliases


def build_candidates(yt_rows, oy_rows, aliases):
    brands: dict[str, list] = defaultdict(list)
    brand_display: dict[str, str] = {}
    for row in oy_rows:
        brand = key(row["brand_name_ko"])
        if brand:
            brands[brand].append(row)
            brand_display[brand] = row["brand_name_ko"]

    counts: dict[str, int] = defaultdict(int)
    yt_display: dict[str, str] = {}
    candidates: list[tuple] = []
    unmatched: list[tuple] = []
    for yt in yt_rows:
        yt_brand = key(yt["brand_name"])
        counts[yt_brand] += 1
        yt_display[yt_brand] = yt["brand_name"]
        if yt_brand in UNKNOWN_BRANDS:
            unmatched.append(
                (
                    yt["yt_product_id"],
                    yt["brand_name"],
                    yt["product_name"],
                    yt["option_name"],
                    yt["product_url"],
                    yt["image_url"],
                    "brand_unknown",
                )
            )
            continue
        oy_brand = aliases.get(yt_brand, yt_brand)
        if oy_brand not in brands:
            unmatched.append(
                (
                    yt["yt_product_id"],
                    yt["brand_name"],
                    yt["product_name"],
                    yt["option_name"],
                    yt["product_url"],
                    yt["image_url"],
                    "brand_not_matched",
                )
            )
            continue
        method = "reviewed_brand_alias" if yt_brand in aliases else "same_brand"
        ranked: list[tuple[float, float, object, object | None]] = []
        for oy in brands[oy_brand]:
            product_score = product_ratio(
                yt["product_name"],
                oy["goods_name"],
                yt["brand_name"],
                oy["brand_name_ko"],
            )
            if product_score < 0.55:
                continue
            # An optionless research row is a product-level candidate only. A seller's
            # single option must not be inferred from a missing research option.
            if yt["option_name"]:
                option_scores = [
                    (
                        ratio(
                            yt["option_name"],
                            option["option_name"] or option["shade_name"],
                        ),
                        option,
                    )
                    for option in oy["options"]
                ]
                option_score, best_option = max(
                    option_scores, default=(0.0, None), key=lambda x: x[0]
                )
                if option_score < 0.65:
                    best_option = None
            else:
                option_score, best_option = 0.0, None
            ranked.append((product_score, option_score, oy, best_option))
        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if not ranked:
            unmatched.append(
                (
                    yt["yt_product_id"],
                    yt["brand_name"],
                    yt["product_name"],
                    yt["option_name"],
                    yt["product_url"],
                    yt["image_url"],
                    "product_name_below_candidate_threshold",
                )
            )
        for rank, (product_score, option_score, oy, option) in enumerate(ranked[:5], 1):
            reason = "same reviewed brand; similar product name"
            if product_score == 1.0:
                reason = "same reviewed brand; exact normalized product name"
            if yt["option_name"] and option is None:
                reason += "; option needs review"
            elif option is not None:
                reason += "; similar option name"
            candidates.append(
                (
                    yt["yt_product_id"],
                    yt["brand_name"],
                    yt["product_name"],
                    yt["option_name"],
                    oy["goods_no"],
                    oy["brand_name_ko"],
                    oy["goods_name"],
                    option["option_id"] if option is not None else None,
                    option["option_name"] if option is not None else None,
                    rank,
                    round(product_score, 4),
                    round(option_score, 4),
                    method,
                    reason,
                )
            )

    brand_review = []
    for brand, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
        if brand in UNKNOWN_BRANDS or brand in brands or brand in aliases:
            continue
        suggestions = sorted(
            brand_display,
            key=lambda candidate: ratio(yt_display[brand], brand_display[candidate]),
            reverse=True,
        )[:5]
        brand_review.append(
            (
                yt_display[brand],
                count,
                " | ".join(brand_display[item] for item in suggestions),
            )
        )
    return candidates, brand_review, unmatched


def write_csv(path: Path, columns: tuple[str, ...], rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)


async def run(args: argparse.Namespace) -> None:
    aliases = load_aliases(args.brand_aliases)
    if args.host not in ("127.0.0.1", "localhost"):
        raise ValueError("Only a local PostgreSQL host is supported")
    password = getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
    )
    try:
        if not await conn.fetchval(
            "SELECT to_regclass('public.yt_oy_product_match') IS NOT NULL"
        ):
            raise ValueError("Apply Alembic revision 0015 before matching")
        yt_rows = await conn.fetch(
            "SELECT yt_product_id, brand_name, product_name, option_name, product_url, image_url FROM public.raw_yt_product ORDER BY yt_product_id"
        )
        oy_products = await conn.fetch(
            """SELECT p.goods_no, p.goods_name, b.brand_name_ko
               FROM public.raw_oy_product p
               JOIN public.raw_oy_brand b ON b.brand_code = p.brand_code
               WHERE p.delisted_at IS NULL AND p.goods_name IS NOT NULL"""
        )
        oy_options = await conn.fetch(
            "SELECT goods_no, option_id, option_name, shade_name FROM public.raw_oy_product_option WHERE delisted_at IS NULL"
        )
        options_by_goods = defaultdict(list)
        for option in oy_options:
            options_by_goods[option["goods_no"]].append(option)
        oy_rows = [
            dict(row, options=options_by_goods[row["goods_no"]]) for row in oy_products
        ]
        candidates, brands, unmatched = build_candidates(yt_rows, oy_rows, aliases)
        write_csv(
            args.report_dir / "product_candidates.csv", CANDIDATE_COLUMNS, candidates
        )
        write_csv(args.report_dir / "brand_review.csv", BRAND_COLUMNS, brands)
        write_csv(
            args.report_dir / "unknown_brand_products.csv",
            UNMATCHED_COLUMNS,
            [row for row in unmatched if row[-1] == "brand_unknown"],
        )
        write_csv(
            args.report_dir / "unmatched_products.csv", UNMATCHED_COLUMNS, unmatched
        )
        print(
            f"YouTube products {len(yt_rows):,}; Olive Young products {len(oy_rows):,}; "
            f"candidates {len(candidates):,}; unmatched brands {len(brands):,}; "
            f"products without candidates {len(unmatched):,}"
        )
        print(f"Review files: {args.report_dir}")
        if not args.apply:
            print("Preview complete; no database rows were written or confirmed")
            return
        async with conn.transaction():
            inserted = 0
            for row in candidates:
                status = await conn.execute(
                    """INSERT INTO public.yt_oy_product_match
                       (yt_product_id, oy_goods_no, oy_option_id, candidate_rank,
                        match_method, similarity_score, match_reason, rule_version)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                       ON CONFLICT (yt_product_id, oy_goods_no, oy_option_id) DO NOTHING""",
                    row[0],
                    row[4],
                    row[7],
                    row[9],
                    row[12],
                    row[10],
                    row[13],
                    RULE_VERSION,
                )
                inserted += int(status == "INSERT 0 1")
        print(f"Stored {inserted:,} new candidates; no matches were auto-confirmed")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--brand-aliases", type=Path)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
