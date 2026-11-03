"""Build the serving catalog from the Olive Young makeup v29 CSV snapshot.

Does not invent colors. Skincare v1 and makeup v23 are not loaded. Rows without a
positive price are skipped, matching ``validate_catalog``.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from app.schemas.catalog import CatalogBundle
from app.schemas.oy_catalog import (
    OyProductInput,
    OyShadeInput,
    catalog_category,
    derive_care_tags,
)
from app.services.catalog_service import validate_catalog
from app.services.oy_catalog import build_oy_catalog

csv.field_size_limit(50_000_000)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _latest(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    chosen: dict[str, dict[str, str]] = {}
    for row in rows:
        token = row.get(key) or ""
        if not token:
            continue
        previous = chosen.get(token)
        stamp = row.get("collected_at") or ""
        previous_stamp = (previous.get("collected_at") or "") if previous else ""
        if previous is None or stamp >= previous_stamp:
            chosen[token] = row
    return chosen


def _products_from_dir(folder: Path) -> list[OyProductInput]:
    products = _read(folder / "product.csv")
    categories = {row["category_no"]: row for row in _read(folder / "category.csv")}
    brands = {
        row["brand_code"]: row.get("brand_name_ko") or row["brand_code"]
        for row in _read(folder / "brand.csv")
    }
    options = _read(folder / "product_option.csv")
    color_path = folder / "option_color.csv"
    colors = _latest(_read(color_path), "option_id") if color_path.exists() else {}
    prices = _latest(
        [row for row in _read(folder / "price_snapshot.csv") if row.get("is_latest") == "True"],
        "option_id",
    )
    images = [
        row
        for row in _read(folder / "image.csv")
        if row.get("image_type") == "thumbnail" and not row.get("option_id")
    ]
    thumb: dict[str, str] = {}
    for row in sorted(images, key=lambda item: int(item.get("sort_seq") or "0")):
        thumb.setdefault(row["goods_no"], row["image_url"])
    textures = (
        _latest(_read(folder / "product_texture.csv"), "goods_no")
        if (folder / "product_texture.csv").exists()
        else {}
    )
    notices = _latest(_read(folder / "product_notice.csv"), "goods_no")
    options_by_goods: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in options:
        options_by_goods[row["goods_no"]].append(row)

    built: list[OyProductInput] = []
    seen_goods: set[str] = set()
    for product in products:
        if product.get("delisted_at") or product["goods_no"] in seen_goods:
            continue
        seen_goods.add(product["goods_no"])
        category = categories.get(product.get("category_no") or "")
        if category is None:
            continue
        mapped = catalog_category(category["category_name"], category.get("category_path") or "")
        if mapped is None:
            continue
        shades: list[OyShadeInput] = []
        for option in options_by_goods.get(product["goods_no"], []):
            color = colors.get(option["option_id"], {})
            price = prices.get(option["option_id"], {})
            shades.append(
                OyShadeInput(
                    option_id=option["option_id"],
                    shade_name=(
                        option.get("shade_name") or option.get("option_name") or option["option_id"]
                    ),
                    shade_code=option.get("shade_code") or None,
                    hex_code=color.get("hex_code") or None,
                    sale_price=_int(price.get("sale_price")),
                    list_price=_int(price.get("list_price")),
                )
            )
        notice = notices.get(product["goods_no"], {})
        texture = textures.get(product["goods_no"], {})
        brand_code = product.get("brand_code") or ""
        built.append(
            OyProductInput(
                goods_no=product["goods_no"],
                brand_name=brands.get(brand_code, "") or brand_code,
                category_name=mapped,
                goods_name=product["goods_name"],
                product_url=product.get("product_url") or "",
                image_url=thumb.get(product["goods_no"]),
                volume=notice.get("volume") or None,
                texture_code=texture.get("texture_code") or None,
                shades=tuple(shades),
                care_tags=derive_care_tags(product["goods_name"], mapped),
            )
        )
    return built


def _int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makeup-v29", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    args = parser.parse_args()

    rows = _products_from_dir(args.makeup_v29)
    built = build_oy_catalog(rows)
    seed = CatalogBundle(products=built.products).model_dump(mode="json", by_alias=True)
    client = json.loads(json.dumps(seed))
    urls = {f"oy-{row.goods_no.lower()}"[:64]: row.product_url for row in rows}
    for product in client["products"]:
        url = urls.get(product["id"])
        if url:
            product["sourceUrl"] = url
        for shade in product["shades"]:
            shade["measureMethod"] = "estimated"
    args.seed.parent.mkdir(parents=True, exist_ok=True)
    args.client.parent.mkdir(parents=True, exist_ok=True)
    args.seed.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    args.client.write_text(json.dumps(client, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_catalog(CatalogBundle.model_validate(seed))
    print(
        json.dumps(
            {
                "v29": len(rows),
                "products": len(built.products),
                "arProducts": built.ar_products,
                "arShades": built.ar_shades,
                "listedWithoutColor": built.listed_without_color,
                "skippedWithoutPrice": built.skipped_without_price,
                "skippedUnknownCategory": built.skipped_unknown_category,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
