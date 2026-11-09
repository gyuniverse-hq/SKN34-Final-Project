"""Add selected non-Olive-Young video products to the serving seed.

Run from backend/api. This reads the local YouTube source and writes a review
catalog file; the database is not changed until seed_catalog imports that file.
Rows with verified photos/prices use the reviewed CSV. Other explicitly selected
rows use the raw research price and leave the product photo empty.
"""

import argparse
import asyncio
import csv
import getpass
import json
import os
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

API_ROOT = Path(__file__).resolve().parents[3] / "backend" / "api"
sys.path.insert(0, str(API_ROOT))

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog

FIELDS = (
    "yt_product_id",
    "source_brand",
    "source_product_name",
    "source_option_name",
    "verified_name",
    "category",
    "texture",
    "volume",
    "price_krw",
    "product_page",
    "image_url",
    "verified_at",
)
RAW_FIELDS = ("yt_product_id", "category")
EXCLUSION_FIELDS = (
    "yt_product_id",
    "brand_name",
    "product_name",
    "exclusion_reason",
)
SERVING_CATEGORIES = {"lip", "cheek", "eye", "base", "skincare", "suncare"}


def checked_url(value: str, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} must be a verified HTTPS URL")
    return value


def read_review(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Expected reviewed CSV columns: {FIELDS}")
        rows = list(reader)
    if len({row["yt_product_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate YouTube product IDs in reviewed CSV")
    for row in rows:
        product_id = row["yt_product_id"]
        required = (
            "source_brand",
            "source_product_name",
            "verified_name",
            "category",
            "volume",
            "price_krw",
            "product_page",
            "image_url",
            "verified_at",
        )
        if not product_id.startswith("yt-") or any(
            not row[field] for field in required
        ):
            raise ValueError(f"Incomplete reviewed row: {product_id}")
        if int(row["price_krw"]) <= 0:
            raise ValueError(f"Invalid verified price: {product_id}")
        if date.fromisoformat(row["verified_at"]) > date.today():
            raise ValueError(f"Future verification date: {product_id}")
        checked_url(row["product_page"], "product_page")
        checked_url(row["image_url"], "image_url")
    return rows


def read_exclusions(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != EXCLUSION_FIELDS:
            raise ValueError(f"Expected exclusion CSV columns: {EXCLUSION_FIELDS}")
        rows = list(reader)
    exclusions = {row["yt_product_id"]: row for row in rows}
    if len(exclusions) != len(rows):
        raise ValueError("Duplicate YouTube product IDs in exclusion CSV")
    for row in rows:
        if (
            not row["yt_product_id"].startswith("yt-")
            or not row["exclusion_reason"].strip()
        ):
            raise ValueError(f"Invalid exclusion row: {row['yt_product_id']}")
    return exclusions


def read_raw_selection(
    path: Path, excluded_ids: set[str]
) -> tuple[list[dict[str, str]], int]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != RAW_FIELDS:
            raise ValueError(f"Expected raw selection columns: {RAW_FIELDS}")
        rows = list(reader)
    ids = [row["yt_product_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate YouTube product IDs in raw selection")
    skipped = sum(row["yt_product_id"] in excluded_ids for row in rows)
    rows = [row for row in rows if row["yt_product_id"] not in excluded_ids]
    for row in rows:
        if not row["yt_product_id"].startswith("yt-"):
            raise ValueError(f"Invalid YouTube product ID: {row['yt_product_id']}")
        if row["category"] not in SERVING_CATEGORIES:
            raise ValueError(f"Invalid serving category: {row['category']}")
    return rows, skipped


def category_tag(category: str) -> str:
    return (category.split(">")[-1].strip() or category.split(">", 1)[0].strip())[:80]


def optional_source_text(value: str | None) -> str:
    text = (value or "").strip()
    return "" if text.casefold() == "n" else text


async def build(args: argparse.Namespace) -> None:
    reviewed = read_review(args.reviewed)
    exclusions = read_exclusions(args.excluded_products)
    if {row["yt_product_id"] for row in reviewed} & exclusions.keys():
        raise ValueError("Reviewed product is listed as a non-product exclusion")
    raw_selection, excluded_count = read_raw_selection(
        args.raw_selection, set(exclusions)
    )
    selected_ids = [row["yt_product_id"] for row in reviewed + raw_selection]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("A product is selected in both reviewed files")
    source_check_ids = list(dict.fromkeys([*selected_ids, *exclusions]))
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
        "Local PostgreSQL password: "
    )
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=args.port,
        user="vishue",
        password=password,
        database=args.database,
        server_settings={"application_name": "yt_verified_catalog_read_only"},
    )
    try:
        async with conn.transaction(readonly=True):
            source = {
                row["yt_product_id"]: dict(row)
                for row in await conn.fetch(
                    "SELECT yt_product_id, brand_name, product_name, option_name, category, "
                    "price_krw, price_type, volume, description FROM raw_yt_product "
                    "WHERE yt_product_id = ANY($1::text[])",
                    source_check_ids,
                )
            }
            already_oy = {
                row["yt_product_id"]
                for row in await conn.fetch(
                    "SELECT yt_product_id FROM yt_oy_product_match "
                    "WHERE decision_status = 'confirmed' AND yt_product_id = ANY($1::text[])",
                    selected_ids,
                )
            }
    finally:
        await conn.close()

    for product_id, exclusion in exclusions.items():
        raw = source.get(product_id)
        if raw is None:
            raise ValueError(f"Excluded source product is missing: {product_id}")
        if (raw["brand_name"], raw["product_name"]) != (
            exclusion["brand_name"],
            exclusion["product_name"],
        ):
            raise ValueError(f"Excluded source identity changed: {product_id}")

    additions = []
    for row in reviewed:
        product_id = row["yt_product_id"]
        raw = source.get(product_id)
        if raw is None:
            raise ValueError(f"Missing source product: {product_id}")
        if product_id in already_oy:
            raise ValueError(f"Already linked to an Olive Young product: {product_id}")
        if (raw["brand_name"], raw["product_name"], raw["option_name"] or "") != (
            row["source_brand"],
            row["source_product_name"],
            row["source_option_name"],
        ):
            raise ValueError(f"Source identity changed: {product_id}")
        name = row["verified_name"]
        additions.append(
            {
                "id": product_id,
                "brand": row["source_brand"],
                "name": name,
                "nameKo": name,
                "category": row["category"],
                "makeupZone": None,
                "texture": row["texture"] or None,
                "priceKRW": int(row["price_krw"]),
                "volume": row["volume"],
                "shades": [],
                "description": "",
                "keyIngredients": [],
                "tags": ["youtube", "verified"],
                "imageUrl": row["image_url"],
                "searchKeyword": f"{row['source_brand']} {name}",
            }
        )

    for row in raw_selection:
        product_id = row["yt_product_id"]
        raw = source.get(product_id)
        if raw is None:
            raise ValueError(f"Missing source product: {product_id}")
        if product_id in already_oy:
            raise ValueError(f"Already linked to an Olive Young product: {product_id}")
        if raw["brand_name"].strip() in {"", "확인 필요"}:
            raise ValueError(f"Unidentified brand: {product_id}")
        price = raw["price_krw"]
        if price is None or price <= 0:
            raise ValueError(f"Missing positive source price: {product_id}")
        name = raw["product_name"].strip()
        if not name:
            raise ValueError(f"Missing source product name: {product_id}")
        option = optional_source_text(raw["option_name"])
        volume = optional_source_text(raw["volume"])
        description = optional_source_text(raw["description"])
        display_name = (
            name
            if not option or option.casefold() in name.casefold()
            else f"{name} {option}"
        )
        if len(display_name) > 200:
            raise ValueError(f"Serving product name is too long: {product_id}")
        additions.append(
            {
                "id": product_id,
                "brand": raw["brand_name"],
                "name": display_name,
                "nameKo": display_name,
                "category": row["category"],
                # The app only accepts a try-on zone with a measured shade and texture.
                "makeupZone": None,
                "texture": None,
                "priceKRW": price,
                "volume": volume,
                "shades": [],
                "description": description,
                "keyIngredients": [],
                "tags": [
                    "youtube",
                    category_tag(raw["category"] or row["category"]),
                    *(
                        ["price_estimated"]
                        if "추정" in (raw["price_type"] or "")
                        else []
                    ),
                ],
                "imageUrl": "",
                "searchKeyword": f"{raw['brand_name']} {display_name}"[:200],
            }
        )

    base = json.loads(args.base.read_text(encoding="utf-8"))
    existing = {item["id"]: item for item in base["products"]}
    for addition in additions:
        existing[addition["id"]] = addition
    base["products"] = list(existing.values())
    validate_catalog(CatalogBundle.model_validate(base))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Selected non-OY products: {len(reviewed)} with verified assets, "
        f"{len(raw_selection)} with source prices; non-product exclusions: "
        f"{len(exclusions)} in manifest, {excluded_count} skipped from selection; "
        f"catalog products: {len(base['products'])}"
    )
    print(f"Wrote review catalog: {args.output}; no database rows were written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reviewed",
        type=Path,
        default=Path(__file__).with_name("verified_non_oy_products.csv"),
    )
    parser.add_argument(
        "--raw-selection",
        type=Path,
        default=Path(__file__).with_name("non_oy_source_price.csv"),
    )
    parser.add_argument(
        "--excluded-products",
        type=Path,
        default=Path(__file__).with_name("non_product_exclusions.csv"),
    )
    parser.add_argument("--base", type=Path, default=API_ROOT / "seed" / "catalog.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--port", type=int, default=15432)
    asyncio.run(build(parser.parse_args()))


if __name__ == "__main__":
    main()
