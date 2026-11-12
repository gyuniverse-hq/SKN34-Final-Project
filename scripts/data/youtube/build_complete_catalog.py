"""Build a review catalog by appending complete YouTube enrichment rows.

This creates a full catalog JSON for review/import; it does not write to PostgreSQL.
Tool products use the serving category ``tool`` and the ``youtube/tool`` tags.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3] / "backend" / "api"
sys.path.insert(0, str(API_ROOT))

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog

VALID_CATEGORIES = {"lip", "cheek", "eye", "base", "skincare", "suncare", "tool"}
DECISION_FIELDS = {
    "yt_product_id",
    "item_type",
    "serving_category",
    "decision",
    "final_tags",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_decisions(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = DECISION_FIELDS - fields
        if missing:
            raise ValueError(f"Decision CSV is missing columns: {sorted(missing)}")
        rows = list(reader)
    decisions = {row["yt_product_id"]: row for row in rows}
    if len(decisions) != len(rows):
        raise ValueError("Duplicate YouTube IDs in decision CSV")
    return decisions


def category_from_tags(value: str, product_id: str) -> str:
    try:
        tags = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid tags JSON: {product_id}") from exc
    category = tags[1] if isinstance(tags, list) and len(tags) > 1 else ""
    if category not in VALID_CATEGORIES - {"tool"}:
        raise ValueError(f"Invalid non-tool category {category!r}: {product_id}")
    return category


def build(args: argparse.Namespace) -> None:
    base = json.loads(args.base_catalog.read_text(encoding="utf-8"))
    bundle = CatalogBundle.model_validate(base)
    complete = [
        row
        for row in read_csv(args.enrichment)
        if row.get("lookup_status") == "complete"
    ]
    decisions = read_decisions(args.decisions)
    tool_ids = {row["yt_product_id"] for row in complete if row.get("is_tool") == "yes"}
    if tool_ids != set(decisions):
        missing = sorted(tool_ids - set(decisions))
        extra = sorted(set(decisions) - tool_ids)
        raise ValueError(f"Tool decisions must cover exactly {len(tool_ids)} complete tool rows; missing={missing}; extra={extra}")

    products = list(bundle.products)
    existing_ids = {product.id for product in products}
    additions = []
    for row in complete:
        product_id = row["yt_product_id"]
        if product_id in existing_ids:
            raise ValueError(f"YouTube product already exists in base catalog: {product_id}")
        if not row.get("selected_brand") or not row.get("selected_product_name"):
            raise ValueError(f"Complete row lacks selected identity: {product_id}")
        try:
            price = int(row.get("price_krw", ""))
        except ValueError as exc:
            raise ValueError(f"Invalid price: {product_id}") from exc
        if price <= 0:
            raise ValueError(f"Non-positive price: {product_id}")
        image_url = row.get("image_url", "").strip()
        if not image_url.startswith("https://"):
            raise ValueError(f"Invalid image URL: {product_id}")

        if row.get("is_tool") == "yes":
            review = decisions[product_id]
            if review["decision"] != "load":
                raise ValueError(f"Tool row is not approved for loading: {product_id}")
            item_type = review["item_type"]
            if item_type not in {"tool", "cosmetic"}:
                raise ValueError(f"Invalid reviewed item type: {product_id}")
            category = "tool" if item_type == "tool" else review["serving_category"]
            expected_tags = ["youtube", "tool" if item_type == "tool" else category]
            try:
                actual_tags = json.loads(review["final_tags"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid reviewed tags: {product_id}") from exc
            if actual_tags != expected_tags:
                raise ValueError(f"Reviewed tags do not match item type/category: {product_id}")
        else:
            category = category_from_tags(row.get("tags", ""), product_id)
            expected_tags = ["youtube", category]
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid serving category {category!r}: {product_id}")

        name = row["selected_product_name"].strip()
        additions.append(
            {
                "id": product_id,
                "brand": row["selected_brand"].strip(),
                "name": name,
                "nameKo": name,
                "category": category,
                "makeupZone": None,
                "texture": None,
                "priceKRW": price,
                "volume": "" if row.get("is_tool") == "yes" else row.get("volume", "").strip(),
                "shades": [],
                "description": "",
                "keyIngredients": [],
                "tags": expected_tags,
                "imageUrl": image_url,
                "searchKeyword": f"{row['selected_brand'].strip()} {name}",
            }
        )
        existing_ids.add(product_id)

    combined = CatalogBundle.model_validate(
        {
            "products": [*products, *additions],
            "looks": bundle.looks,
            "stores": bundle.stores,
        }
    )
    validate_catalog(combined)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(combined.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    tool_count = sum(product["category"] == "tool" for product in additions)
    print(
        f"Complete YouTube rows: {len(complete)}; appended: {len(additions)}; "
        f"tool category: {tool_count}; base products: {len(products)}; "
        f"review catalog products: {len(combined.products)}"
    )
    print(f"Review catalog: {args.output}; database rows were not written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enrichment", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument(
        "--base-catalog", type=Path, default=API_ROOT / "seed" / "catalog.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=API_ROOT / "seed" / "catalog-youtube-v31-review.json",
    )
    build(parser.parse_args())


if __name__ == "__main__":
    main()
