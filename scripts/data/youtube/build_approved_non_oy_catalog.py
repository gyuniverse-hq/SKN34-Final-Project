"""Build a review catalog from user-approved non-Olive-Young YouTube products.

This script only reads the local database and writes a review JSON. Importing that
JSON with app.jobs.seed_catalog is a separate, full-catalog replacement operation.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

import asyncpg

API_ROOT = Path(__file__).resolve().parents[3] / "backend" / "api"
sys.path.insert(0, str(API_ROOT))

FIELDS = (
    "source_yt_product_ids",
    "serving_product_id",
    "action",
    "brand",
    "name",
    "category",
    "price_krw",
    "volume",
    "image_url",
    "evidence_url",
)
VALID_CATEGORIES = {"lip", "cheek", "eye", "base", "skincare", "suncare"}
EXPECTED_ROWS = 39
EXPECTED_INSERTS = 35
EXPECTED_UPDATES = 4


def read_approved(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Expected reviewed CSV columns: {FIELDS}")
        rows = [
            {key: (value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} approved catalog rows, got {len(rows)}")
    if len({row["serving_product_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate serving_product_id in approved CSV")
    actions = {action: sum(row["action"] == action for row in rows) for action in ("insert", "update")}
    if actions != {"insert": EXPECTED_INSERTS, "update": EXPECTED_UPDATES}:
        raise ValueError(f"Expected 35 inserts and 4 updates, got {actions}")
    for row in rows:
        source_ids = row["source_yt_product_ids"].split(";")
        if not row["serving_product_id"].startswith("yt-") or not source_ids:
            raise ValueError(f"Invalid source or serving ID: {row}")
        if row["action"] not in {"insert", "update"}:
            raise ValueError(f"Invalid action for {row['serving_product_id']}")
        if not row["brand"] or not row["name"] or row["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Missing/invalid catalog fields: {row['serving_product_id']}")
        if int(row["price_krw"]) <= 0:
            raise ValueError(f"Invalid price: {row['serving_product_id']}")
        if len(row["name"]) > 200:
            raise ValueError(f"Serving name is too long: {row['serving_product_id']}")
        for field in ("image_url", "evidence_url"):
            if row[field]:
                parsed = urlparse(row[field])
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError(f"{field} must be a verified HTTPS URL")
    return rows


async def build(args: argparse.Namespace) -> None:
    rows = read_approved(args.approved)
    source_ids = sorted(
        {
            source_id
            for row in rows
            for source_id in row["source_yt_product_ids"].split(";")
        }
    )
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
        "Local PostgreSQL password: "
    )
    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=args.port,
        database=args.database,
        user="vishue",
        password=password,
        server_settings={"application_name": "yt_approved_catalog_read_only"},
    )
    try:
        async with conn.transaction(readonly=True):
            found = {
                row["yt_product_id"]
                for row in await conn.fetch(
                    "SELECT yt_product_id FROM public.raw_yt_product "
                    "WHERE yt_product_id = ANY($1::text[])",
                    source_ids,
                )
            }
            missing = sorted(set(source_ids) - found)
            if missing:
                raise ValueError(f"YouTube source rows are missing: {missing}")
            confirmed_oy = {
                row["yt_product_id"]
                for row in await conn.fetch(
                    "SELECT yt_product_id FROM public.yt_oy_product_match "
                    "WHERE decision_status = 'confirmed' AND yt_product_id = ANY($1::text[])",
                    source_ids,
                )
            }
            if confirmed_oy:
                raise ValueError(
                    "Approved non-OY items include confirmed Olive Young matches: "
                    f"{sorted(confirmed_oy)}"
                )
    finally:
        await conn.close()

    catalog = json.loads(args.base.read_text(encoding="utf-8"))
    products = {product["id"]: product for product in catalog["products"]}
    insert_ids = []
    update_ids = []
    for row in rows:
        product_id = row["serving_product_id"]
        existing = products.get(product_id)
        if row["action"] == "insert" and existing is not None:
            raise ValueError(f"Insert ID already exists in base catalog: {product_id}")
        if row["action"] == "update" and existing is None:
            raise ValueError(f"Update target is absent from base catalog: {product_id}")
        if row["action"] == "insert":
            product = {
                "id": product_id,
                "brand": row["brand"],
                "name": row["name"],
                "nameKo": row["name"],
                "category": row["category"],
                "makeupZone": None,
                "texture": None,
                "priceKRW": int(row["price_krw"]),
                "volume": row["volume"],
                "shades": [],
                "description": "",
                "keyIngredients": [],
                "tags": ["youtube", row["category"]],
                "imageUrl": row["image_url"],
                "searchKeyword": f"{row['brand']} {row['name']}"[:200],
            }
            insert_ids.append(product_id)
        else:
            product = dict(existing)
            product.update(
                {
                    "brand": row["brand"],
                    "name": row["name"],
                    "nameKo": row["name"],
                    "category": row["category"],
                    "priceKRW": int(row["price_krw"]),
                    "volume": row["volume"] or existing.get("volume", ""),
                    "imageUrl": row["image_url"] or existing.get("imageUrl", ""),
                    "searchKeyword": f"{row['brand']} {row['name']}"[:200],
                }
            )
            update_ids.append(product_id)
        products[product_id] = product

    catalog["products"] = list(products.values())
    from app.schemas.catalog import CatalogBundle
    from app.services.catalog_service import validate_catalog

    validate_catalog(CatalogBundle.model_validate(catalog))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Approved rows: {len(rows)}; new products: {len(insert_ids)}; "
        f"updated products: {len(update_ids)}"
    )
    print(
        "Approved image URLs: "
        f"{sum(bool(row['image_url']) for row in rows)}; "
        f"missing image URLs: {sum(not row['image_url'] for row in rows)}"
    )
    print(f"Base products: {len(products) - len(insert_ids)}; review products: {len(products)}")
    print(f"Review catalog: {args.output}; database rows were not written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved", type=Path, default=Path(__file__).with_name("approved_non_oy_catalog.csv"))
    parser.add_argument("--base", type=Path, default=API_ROOT / "seed" / "catalog.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--port", type=int, default=15432)
    asyncio.run(build(parser.parse_args()))


if __name__ == "__main__":
    main()
