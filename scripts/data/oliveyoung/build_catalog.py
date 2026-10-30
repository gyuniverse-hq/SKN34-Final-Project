"""Build a reviewable catalog JSON from the Olive Young raw tables.

This is read-only. Run from backend/api with uv. The output is a local file,
not the tracked seed; review it before deciding whether to publish it.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import ssl
import sys
from collections import Counter, defaultdict
from pathlib import Path

import asyncpg

API_ROOT = Path(__file__).resolve().parents[3] / "backend" / "api"
sys.path.insert(0, str(API_ROOT))

from app.schemas.catalog import CatalogBundle  # noqa: E402
from app.services.catalog_service import validate_catalog  # noqa: E402

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
TEXTURES = frozenset({"matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer"})
COLOR_SOURCE_BY_METHOD = {
    "color_chip": "option_chip",
    "swatch": "color_compare",
    "pencil_tip": "product_photo",
}

# These four v29 options are standalone palette accessories, not cosmetic shades.
# Keep the source rows intact; omit them only from this app-facing catalog build.
CATALOG_OPTION_EXCLUSIONS = {
    "A000000174309-047": "standalone palette case (8-pan)",
    "A000000174309-103": "standalone palette case (3-pan)",
    "A000000174309-135": "standalone essential fit brush",
    "A000000174309-140": "standalone gel-tail brush",
}

# App-facing grouping. This is separate from the per-category required-field rules in PostgreSQL.
CATEGORY = {
    "립틴트": ("lip", "lip"),
    "립글로스": ("lip", "lip"),
    "립스틱": ("lip", "lip"),
    "립케어(컬러립밤)": ("lip", "lip"),
    "립케어(보습립밤)": ("lip", None),
    "립케어(기타)": ("lip", None),
    "립라이너": ("lip", None),
    "블러셔": ("cheek", "blush"),
    "하이라이터": ("cheek", None),
    "쉐이딩": ("cheek", None),
    "아이섀도우": ("eye", "eyeshadow"),
    "아이브로우": ("eye", None),
    "아이라이너": ("eye", None),
    "마스카라": ("eye", None),
    "쿠션": ("base", None),
    "프라이머/베이스": ("base", None),
    "파우더/팩트": ("base", None),
    "파운데이션": ("base", None),
    "BB/CC": ("base", None),
    "컨실러": ("base", None),
    "메이크업 픽서": ("base", None),
}


def clean(value: str | None) -> str:
    return " ".join((value or "").replace("■", " ").split())


def build_products(
    raw_products: list[dict],
    rules: dict[str, dict],
    options: list[dict],
    prices: dict[str, dict],
    colors: dict[str, dict],
    textures: dict[str, str | None],
    thumbnails: dict[str, str],
) -> tuple[list[dict], Counter[str]]:
    options_by_goods: dict[str, list[dict]] = defaultdict(list)
    for option in options:
        options_by_goods[option["goods_no"]].append(option)

    products = []
    excluded: Counter[str] = Counter()
    if set(rules) != set(CATEGORY):
        raise ValueError(
            f"Category rule mismatch: missing={sorted(set(CATEGORY) - set(rules))}; "
            f"unexpected={sorted(set(rules) - set(CATEGORY))}"
        )
    for raw in sorted(raw_products, key=lambda row: row["goods_no"]):
        code = raw["std_category_code"]
        rule = rules.get(code)
        if rule is None:
            excluded[f"out_of_scope:{code or '(empty)'}"] += 1
            continue
        goods_no = raw["goods_no"]
        name = clean(raw["goods_name"])
        brand = clean(raw["brand_name_ko"])
        if not name or not brand:
            excluded["missing_name_or_brand"] += 1
            continue
        texture = textures.get(goods_no)
        if texture not in TEXTURES:
            texture = None
        if rule["requires_texture"] and texture is None:
            excluded["missing_required_texture"] += 1
            continue

        latest_prices = []
        shades = []
        seen_shades: set[str] = set()
        missing_required_shade_color = False
        for option in sorted(
            options_by_goods.get(goods_no, []),
            key=lambda row: (
                row["sort_seq"] is None,
                row["sort_seq"] or 0,
                row["option_id"],
            ),
        ):
            option_id = option["option_id"]
            if option_id in CATALOG_OPTION_EXCLUSIONS:
                excluded["standalone_accessory_option"] += 1
                continue
            price = prices.get(option_id)
            if price and isinstance(price["sale_price"], int) and price["sale_price"] > 0:
                latest_prices.append(price["sale_price"])
            is_shade_option = bool(clean(option["shade_code"]) or clean(option["shade_name"]))
            color = colors.get(option_id)
            hex_code = color["hex_code"].upper() if color and color["hex_code"] else ""
            if not HEX.fullmatch(hex_code):
                if rule["requires_color"] and is_shade_option:
                    missing_required_shade_color = True
                continue
            color_source = COLOR_SOURCE_BY_METHOD.get(color["color_method"])
            if color_source is None:
                raise ValueError(f"Unknown color method for {option_id}: {color['color_method']}")
            # The option ID is stable across subsequent catalog rebuilds.
            if option_id in seen_shades:
                continue
            seen_shades.add(option_id)
            shade = {
                "id": option_id,
                "name": clean(option["shade_name"] or option["option_name"])[:100] or option_id,
                "hex": hex_code,
                "measureMethod": "estimated",
                "colorSource": color_source,
            }
            if color["color_confidence"] is not None:
                shade["colorConfidence"] = color["color_confidence"]
            shades.append(shade)

        if rule["requires_color"] and missing_required_shade_color:
            excluded["missing_required_shade_color"] += 1
            continue
        if rule["requires_color"] and not shades:
            excluded["missing_required_color"] += 1
            continue
        if not latest_prices:
            excluded["missing_latest_price"] += 1
            continue
        app_category, zone = CATEGORY[code]
        # A product with an unknown finish must not be rendered with an invented AR texture.
        if not shades or texture is None:
            zone = None
        product_name = name[:200]
        search_keyword = name if brand in name else f"{brand} {name}"
        products.append(
            {
                "id": "oy-" + goods_no.lower(),
                "brand": brand[:100],
                "name": product_name,
                "nameKo": product_name,
                "category": app_category,
                "makeupZone": zone,
                "texture": texture,
                "priceKRW": min(latest_prices),
                "volume": clean(raw["volume"])[:50],
                "shades": shades,
                "description": "",
                # Full ingredient lists are not equivalent to curated key ingredients.
                "keyIngredients": [],
                "tags": [],
                # Use only the product-level thumbnail; option and detail images stay raw-only.
                "imageUrl": thumbnails.get(goods_no, ""),
                "searchKeyword": search_keyword[:200],
            }
        )
    return products, excluded


async def fetch_source(
    conn: asyncpg.Connection,
) -> tuple[list[dict], dict, list[dict], dict, dict, dict, dict]:
    required = (
        "raw_oy_product",
        "raw_oy_product_option",
        "raw_oy_price_snapshot",
        "raw_oy_option_color",
        "raw_oy_product_texture",
        "raw_oy_image",
        "oy_catalog_category_rule",
    )
    for table in required:
        if await conn.fetchval("SELECT to_regclass($1)", f"public.{table}") is None:
            raise ValueError(f"Missing public.{table}; apply Alembic migrations first")
    rules = {
        row["std_category_code"]: dict(row)
        for row in await conn.fetch("SELECT * FROM public.oy_catalog_category_rule")
    }
    products = [
        dict(row)
        for row in await conn.fetch(
            """
            SELECT p.goods_no, p.std_category_code, p.goods_name,
                   b.brand_name_ko, n.volume
            FROM public.raw_oy_product p
            LEFT JOIN public.raw_oy_brand b ON b.brand_code = p.brand_code
            LEFT JOIN public.raw_oy_product_notice n ON n.goods_no = p.goods_no
            """
        )
    ]
    options = [
        dict(row)
        for row in await conn.fetch(
            """
            SELECT option_id, goods_no, option_name, shade_code, shade_name, sort_seq
            FROM public.raw_oy_product_option
            """
        )
    ]
    prices = {
        row["option_id"]: dict(row)
        for row in await conn.fetch(
            """
            SELECT DISTINCT ON (option_id) option_id, sale_price
            FROM public.raw_oy_price_snapshot
            WHERE option_id IS NOT NULL
            ORDER BY option_id, is_latest DESC NULLS LAST, collected_at DESC NULLS LAST,
                     snapshot_id DESC
            """
        )
    }
    colors = {
        row["option_id"]: dict(row)
        for row in await conn.fetch(
            """
            SELECT DISTINCT ON (option_id) option_id, hex_code, color_method, color_confidence
            FROM public.raw_oy_option_color
            ORDER BY option_id, collected_at DESC
            """
        )
    }
    textures = {
        row["goods_no"]: row["texture_code"]
        for row in await conn.fetch(
            """
            SELECT DISTINCT ON (goods_no) goods_no, texture_code
            FROM public.raw_oy_product_texture
            ORDER BY goods_no, collected_at DESC
            """
        )
    }
    thumbnails = {
        row["goods_no"]: row["image_url"]
        for row in await conn.fetch(
            """
            SELECT DISTINCT ON (goods_no) goods_no, image_url
            FROM public.raw_oy_image
            WHERE image_type = 'thumbnail'
              AND goods_no IS NOT NULL
              AND image_url IS NOT NULL
              AND btrim(image_url) <> ''
            ORDER BY goods_no, sort_seq ASC NULLS LAST,
                     collected_at DESC NULLS LAST, image_id DESC
            """
        )
    }
    return products, rules, options, prices, colors, textures, thumbnails


async def run(args: argparse.Namespace) -> None:
    if args.target == "shared":
        if not args.project_ref or args.user != f"postgres.{args.project_ref}":
            raise ValueError("Shared database user and --project-ref must match")
        if not args.host.endswith(".pooler.supabase.com") or args.port != 5432:
            raise ValueError("Shared reads require a Supabase session pooler on port 5432")
        if not args.ssl_ca_file or not args.ssl_ca_file.is_file():
            raise ValueError("Shared reads require an existing --ssl-ca-file")
        ssl_config: ssl.SSLContext | bool = ssl.create_default_context(
            cafile=str(args.ssl_ca_file.resolve())
        )
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        if args.project_ref or args.ssl_ca_file:
            raise ValueError("Shared-only options cannot be used with --target local")
        ssl_config = False
        password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
            "Local PostgreSQL password: "
        )
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=ssl_config,
        server_settings={"application_name": "oy_catalog_build_read_only"},
    )
    try:
        async with conn.transaction(readonly=True):
            raw_products, rules, options, prices, colors, textures, thumbnails = (
                await fetch_source(conn)
            )
    finally:
        await conn.close()

    products, excluded = build_products(
        raw_products, rules, options, prices, colors, textures, thumbnails
    )
    if args.expect_source is not None and len(raw_products) != args.expect_source:
        raise ValueError(f"Source products: expected {args.expect_source}, got {len(raw_products)}")
    if args.expect_products is not None and len(products) != args.expect_products:
        raise ValueError(f"Catalog products: expected {args.expect_products}, got {len(products)}")
    base = json.loads(args.base.read_text(encoding="utf-8"))
    retained = [p for p in base.get("products", []) if not p["id"].startswith("oy-")]
    bundle = {
        "products": retained + products,
        "looks": base.get("looks", []),
        "stores": base.get("stores", []),
    }
    validate_catalog(CatalogBundle.model_validate(bundle))
    print(f"Raw products: {len(raw_products):,}; category rules: {len(rules)}")
    print(f"Catalog products: {len(products):,}; existing non-OY products: {len(retained):,}")
    for reason, count in sorted(excluded.items()):
        print(f"Excluded {reason}: {count:,}")
    print(f"Products without texture: {sum(p['texture'] is None for p in products):,}")
    print(f"Products without shades: {sum(not p['shades'] for p in products):,}")
    print(f"Products with thumbnail URL: {sum(bool(p['imageUrl']) for p in products):,}")
    print(f"Products without thumbnail URL: {sum(not p['imageUrl'] for p in products):,}")
    print(f"Products eligible for AR: {sum(p['makeupZone'] is not None for p in products):,}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote review file: {args.output}")
    else:
        print("Preview only; no file or database rows were written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--project-ref")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_v29")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--ssl-ca-file", type=Path)
    parser.add_argument("--base", type=Path, default=API_ROOT / "seed" / "catalog.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-source", type=int)
    parser.add_argument("--expect-products", type=int)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
