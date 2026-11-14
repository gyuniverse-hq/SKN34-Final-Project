"""Load reviewed official-brand lip shade CSVs into local source/app tables.

Run from backend/api. Without --apply this performs read-only preflight.
The 0022 Alembic revision must already be applied.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import asyncpg

HEX = re.compile(r"^#[0-9A-F]{6}$")
SOURCE_COUNTS = {
    "official_products.csv": 3,
    "official_options.csv": 57,
    "official_option_colors.csv": 57,
    "official_product_textures.csv": 3,
    "serving_shades_preview.csv": 57,
    "serving_products_preview.csv": 3,
}
USER_SHADES = {
    "mac-sheer-146511-570": "#BA634F",
    "mac-tint-147440-946": "#B83A48",
    "estee-gloss-PROD133645-185": "#AC4B4A",
}
ALLOWED_ACTIONS = {
    "preserve_existing",
    "insert_official_css",
    "insert_reviewed_hex",
    "update_reviewed_hex",
}


def read_csv(folder: Path, name: str) -> list[dict[str, str]]:
    with (folder / name).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if name == "official_option_colors.csv" and any(
            field.startswith("source_image_") for field in (reader.fieldnames or [])
        ):
            raise ValueError("Image metadata is not part of the HEX-only source CSV")
        rows = list(reader)
    if len(rows) != SOURCE_COUNTS[name]:
        raise ValueError(f"{name}: expected {SOURCE_COUNTS[name]} rows, found {len(rows)}")
    return rows


def normalized(value: str) -> str:
    value = re.sub(r"^\[[^]]+\]\s*", "", value)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).casefold()


def unique(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        identifier = row[key]
        if not identifier or identifier in output:
            raise ValueError(f"Empty or duplicate {key}: {identifier!r}")
        output[identifier] = row
    return output


def load_files(folder: Path) -> dict:
    items = {name: read_csv(folder, name) for name in SOURCE_COUNTS}
    products = unique(items["official_products.csv"], "source_product_id")
    options = unique(items["official_options.csv"], "source_option_id")
    colors = unique(items["official_option_colors.csv"], "source_option_id")
    textures = unique(items["official_product_textures.csv"], "source_product_id")
    previews = unique(items["serving_shades_preview.csv"], "source_option_id")
    serving_products = unique(items["serving_products_preview.csv"], "serving_product_id")
    if set(options) != set(colors) or set(options) != set(previews):
        raise ValueError("Option/color/serving-preview IDs do not match")
    if set(products) != set(textures):
        raise ValueError("Product/texture IDs do not match")
    if {r["serving_product_id"] for r in products.values()} != set(serving_products):
        raise ValueError("Serving product preview IDs do not match")
    if {key: colors[key]["selected_hex"] for key in USER_SHADES} != USER_SHADES:
        raise ValueError("User-approved HEX colors have changed")
    if sum(c["selected_source"] == "user_reviewed_chip" for c in colors.values()) != 3:
        raise ValueError("Expected exactly three user-reviewed chip colors")
    if sum(p["action"] == "preserve_existing" for p in previews.values()) != 22:
        raise ValueError("Expected to preserve 22 existing app shades")
    for source_id, color in colors.items():
        if not HEX.fullmatch(color["selected_hex"]) or not HEX.fullmatch(color["official_hex"]):
            raise ValueError(f"Invalid hex: {source_id}")
        if color["measure_method"] != "estimated" or color["color_method"] != "color_chip":
            raise ValueError(f"Unexpected color provenance: {source_id}")
        if color["selected_source"] == "user_reviewed_chip":
            if source_id not in USER_SHADES or color["selected_hex"] != USER_SHADES[source_id]:
                raise ValueError(f"Unexpected reviewed HEX: {source_id}")
        elif color["selected_source"] == "official_site_css":
            if color["selected_hex"] != color["official_hex"]:
                raise ValueError(f"CSS color source mismatch: {source_id}")
        else:
            raise ValueError(f"Unexpected source type: {source_id}")
    for source_id, option in options.items():
        product = products.get(option["source_product_id"])
        preview = previews[source_id]
        color = colors[source_id]
        if product is None or option["raw_oy_goods_no"] != product["raw_oy_goods_no"]:
            raise ValueError(f"Option/product mismatch: {source_id}")
        if (
            color["source_url"] != option["source_url"]
            or color["observed_at"] != option["observed_at"]
        ):
            raise ValueError(f"Option/color source mismatch: {source_id}")
        if preview["serving_product_id"] != product["serving_product_id"]:
            raise ValueError(f"Serving product mismatch: {source_id}")
        if preview["selected_hex"] != color["selected_hex"]:
            raise ValueError(f"Serving color mismatch: {source_id}")
        if preview["action"] not in ALLOWED_ACTIONS:
            raise ValueError(f"Unknown action: {source_id}")
        if source_id in USER_SHADES and preview["action"] not in {
            "insert_reviewed_hex",
            "update_reviewed_hex",
        }:
            raise ValueError(f"Reviewed HEX was not selected: {source_id}")
        if len(preview["serving_shade_id"]) > 64:
            raise ValueError(f"Serving shade ID too long: {source_id}")
    for source_id, product in products.items():
        texture = textures[source_id]
        if (
            texture["source_url"] != product["source_url"]
            or texture["observed_at"] != product["observed_at"]
        ):
            raise ValueError(f"Product/texture source mismatch: {source_id}")
    return dict(
        products=products,
        options=options,
        colors=colors,
        textures=textures,
        previews=previews,
        serving_products=serving_products,
    )


async def verify_database(conn: asyncpg.Connection, data: dict) -> tuple[dict, dict]:
    version = await conn.fetchval("SELECT version_num FROM public.alembic_version")
    if version != "0022":
        raise ValueError(f"Alembic revision 0022 required; found {version}")
    for table in (
        "raw_official_product",
        "raw_official_product_option",
    ):
        if not await conn.fetchval("SELECT to_regclass($1)", f"public.{table}"):
            raise ValueError(f"Missing public.{table}")
    product_ids = [p["serving_product_id"] for p in data["products"].values()]
    existing_products = {
        r["id"]: r
        for r in await conn.fetch(
            "SELECT id,brand,name,category,makeup_zone,texture,price_krw "
            "FROM public.products WHERE id=ANY($1)",
            product_ids,
        )
    }
    if len(existing_products) != 3:
        raise ValueError("One of the three serving products is missing")
    raw_goods = {
        r["goods_no"]: r
        for r in await conn.fetch(
            "SELECT p.goods_no,p.std_category_code,p.brand_code,b.brand_name_ko "
            "FROM public.raw_oy_product p JOIN public.raw_oy_brand b USING(brand_code) "
            "WHERE p.goods_no=ANY($1)",
            [p["raw_oy_goods_no"] for p in data["products"].values()],
        )
    }
    for source in data["products"].values():
        current = existing_products[source["serving_product_id"]]
        raw = raw_goods.get(source["raw_oy_goods_no"])
        preview = data["serving_products"][current["id"]]
        texture = data["textures"][source["source_product_id"]]
        if (
            raw is None
            or raw["brand_code"] != source["brand_code"]
            or raw["brand_name_ko"] != source["brand_name"]
        ):
            raise ValueError(f"Raw brand/product changed: {source['source_product_id']}")
        if current["brand"] != source["brand_name"] or current["category"] != "lip":
            raise ValueError(f"Serving brand/category changed: {current['id']}")
        if preview["brand"] != current["brand"] or preview["current_name"] != current["name"]:
            raise ValueError(f"Serving brand/name changed: {current['id']}")
        if str(current["price_krw"]) != preview["current_price_krw"]:
            raise ValueError(f"Serving price changed: {current['id']}")
        if current["makeup_zone"] not in {preview["current_makeup_zone"] or None, "lip"}:
            raise ValueError(f"Serving zone changed: {current['id']}")
        if current["texture"] not in {preview["current_texture"] or None, texture["texture_code"]}:
            raise ValueError(f"Serving texture changed: {current['id']}")
        if (
            preview["proposed_texture"] != texture["texture_code"]
            or preview["proposed_makeup_zone"] != "lip"
        ):
            raise ValueError(f"Product preview/texture mismatch: {current['id']}")
    option_ids = [p["raw_oy_option_id"] for p in data["previews"].values() if p["raw_oy_option_id"]]
    raw_options = {
        r["option_id"]: r
        for r in await conn.fetch(
            "SELECT option_id,goods_no,option_name,shade_name FROM public.raw_oy_product_option "
            "WHERE option_id=ANY($1)",
            option_ids,
        )
    }
    existing_shades = {
        (r["product_id"], r["id"]): r
        for r in await conn.fetch(
            "SELECT product_id,id,name,hex,measure_method,color_source "
            "FROM public.shades WHERE product_id=ANY($1)",
            product_ids,
        )
    }
    for source_id, preview in data["previews"].items():
        option = data["options"][source_id]
        product = data["products"][option["source_product_id"]]
        if oy_id := preview["raw_oy_option_id"]:
            raw = raw_options.get(oy_id)
            if raw is None or raw["goods_no"] != product["raw_oy_goods_no"]:
                raise ValueError(f"Olive Young option mismatch: {source_id}")
            if normalized(raw["shade_name"] or raw["option_name"]) != normalized(
                option["shade_name"]
            ):
                raise ValueError(f"Olive Young shade name mismatch: {source_id}")
        current = existing_shades.get((preview["serving_product_id"], preview["serving_shade_id"]))
        if preview["action"] == "preserve_existing":
            if not current or current["hex"] != preview["current_hex"]:
                raise ValueError(f"Existing app shade changed: {source_id}")
        elif current and current["hex"] != preview["selected_hex"]:
            if preview["action"] != "update_reviewed_hex":
                raise ValueError(f"Conflicting app shade already exists: {source_id}")
        elif current and normalized(current["name"]) != normalized(option["shade_name"]):
            raise ValueError(f"Existing app shade name changed: {source_id}")
    return existing_products, existing_shades


async def apply(conn: asyncpg.Connection, data: dict, existing_shades: dict) -> Counter:
    counts: Counter = Counter()
    for p in data["products"].values():
        texture = data["textures"][p["source_product_id"]]
        await conn.execute(
            """INSERT INTO public.raw_official_product
               (source_product_id,raw_oy_goods_no,serving_product_id,brand_code,
                brand_name,product_name,category,texture_code,judge_step,judge_reason,
                source_url,observed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT (source_product_id) DO UPDATE SET
                raw_oy_goods_no=EXCLUDED.raw_oy_goods_no,
                serving_product_id=EXCLUDED.serving_product_id,
                brand_code=EXCLUDED.brand_code,brand_name=EXCLUDED.brand_name,
                product_name=EXCLUDED.product_name,category=EXCLUDED.category,
                texture_code=EXCLUDED.texture_code,
                judge_step=EXCLUDED.judge_step,
                judge_reason=EXCLUDED.judge_reason,
                source_url=EXCLUDED.source_url,observed_at=EXCLUDED.observed_at""",
            p["source_product_id"],
            p["raw_oy_goods_no"],
            p["serving_product_id"],
            p["brand_code"],
            p["brand_name"],
            p["product_name"],
            p["category"],
            texture["texture_code"],
            texture["judge_step"],
            texture["judge_reason"],
            p["source_url"],
            date.fromisoformat(p["observed_at"]),
        )
        counts["source_products"] += 1
    for row in data["options"].values():
        preview = data["previews"][row["source_option_id"]]
        color = data["colors"][row["source_option_id"]]
        await conn.execute(
            """INSERT INTO public.raw_official_product_option
               (source_option_id,source_product_id,raw_oy_option_id,serving_shade_id,
                shade_code,shade_name,option_name,official_sku_base_id,official_sku_id,
                selected_hex,official_hex,lab_l,lab_a,lab_b,color_method,
                color_confidence,measure_method,selected_source,source_url,observed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                       $16,$17,$18,$19,$20)
               ON CONFLICT (source_option_id) DO UPDATE SET
                source_product_id=EXCLUDED.source_product_id,
                raw_oy_option_id=EXCLUDED.raw_oy_option_id,
                serving_shade_id=EXCLUDED.serving_shade_id,
                shade_code=EXCLUDED.shade_code,shade_name=EXCLUDED.shade_name,
                option_name=EXCLUDED.option_name,
                official_sku_base_id=EXCLUDED.official_sku_base_id,
                official_sku_id=EXCLUDED.official_sku_id,
                selected_hex=EXCLUDED.selected_hex,
                official_hex=EXCLUDED.official_hex,
                lab_l=EXCLUDED.lab_l,lab_a=EXCLUDED.lab_a,lab_b=EXCLUDED.lab_b,
                color_method=EXCLUDED.color_method,
                color_confidence=EXCLUDED.color_confidence,
                measure_method=EXCLUDED.measure_method,
                selected_source=EXCLUDED.selected_source,
                source_url=EXCLUDED.source_url,observed_at=EXCLUDED.observed_at""",
            row["source_option_id"],
            row["source_product_id"],
            preview["raw_oy_option_id"] or None,
            preview["serving_shade_id"],
            row["shade_code"],
            row["shade_name"],
            row["option_name"],
            row["official_sku_base_id"] or None,
            row["official_sku_id"] or None,
            color["selected_hex"],
            color["official_hex"],
            float(color["lab_l"]) if color["lab_l"] else None,
            float(color["lab_a"]) if color["lab_a"] else None,
            float(color["lab_b"]) if color["lab_b"] else None,
            color["color_method"],
            float(color["color_confidence"]) if color["color_confidence"] else None,
            color["measure_method"],
            color["selected_source"],
            row["source_url"],
            date.fromisoformat(row["observed_at"]),
        )
        counts["source_options"] += 1
    for source_id, product in data["products"].items():
        await conn.execute(
            "UPDATE public.products SET makeup_zone='lip',texture=$2 WHERE id=$1",
            product["serving_product_id"],
            data["textures"][source_id]["texture_code"],
        )
    positions = {
        p["serving_product_id"]: (
            await conn.fetchval(
                "SELECT COALESCE(MAX(position), -1) FROM public.shades WHERE product_id=$1",
                p["serving_product_id"],
            )
        )
        for p in data["products"].values()
    }
    new_names: dict[str, list[str]] = defaultdict(list)
    for source_id, row in data["options"].items():
        preview = data["previews"][source_id]
        color = data["colors"][source_id]
        pid, sid = preview["serving_product_id"], preview["serving_shade_id"]
        current = existing_shades.get((pid, sid))
        if preview["action"] == "preserve_existing":
            counts["serving_preserved"] += 1
            continue
        if current is None:
            positions[pid] += 1
            await conn.execute(
                """INSERT INTO public.shades
                   (product_id,id,position,name,hex,measure_method,color_source,color_confidence)
                   VALUES ($1,$2,$3,$4,$5,'estimated','option_chip',$6)""",
                pid,
                sid,
                positions[pid],
                row["shade_name"],
                color["selected_hex"],
                float(color["color_confidence"]) if color["color_confidence"] else None,
            )
            new_names[pid].append(row["shade_name"])
            counts["serving_inserted"] += 1
        elif preview["action"] == "update_reviewed_hex":
            await conn.execute(
                """UPDATE public.shades SET hex=$3,measure_method='estimated',
                   color_source='option_chip',color_confidence=$4
                   WHERE product_id=$1 AND id=$2""",
                pid,
                sid,
                color["selected_hex"],
                float(color["color_confidence"]),
            )
            counts["serving_hex_updated"] += 1
        else:
            counts["serving_already_inserted"] += 1
    for pid, names in new_names.items():
        await conn.execute(
            "UPDATE public.products SET search_text=COALESCE(search_text,'') || ' ' || $2 "
            "WHERE id=$1",
            pid,
            " ".join(names).lower(),
        )
    return counts


async def run(args: argparse.Namespace) -> None:
    folder = args.input_dir.resolve()
    data = load_files(folder)
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
        server_settings={"application_name": "official_brand_shade_load"},
    )
    try:
        async with conn.transaction(readonly=not args.apply):
            _, current_shades = await verify_database(conn, data)
            actions = Counter(r["action"] for r in data["previews"].values())
            print(
                f"Official products 3; options 57; colors 57; textures 3; actions {dict(actions)}"
            )
            print("Existing serving shades:", len(current_shades))
            if args.apply:
                counts = await apply(conn, data, current_shades)
                print("Committed source/app changes:", dict(counts))
            else:
                print("Preflight passed; no database rows were written")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.database != "vishue_db" or args.port != 15432 or args.user != "vishue":
        raise ValueError("This reviewed snapshot is restricted to the local vishue_db")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
