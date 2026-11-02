"""Map Olive Young raw rows onto serving catalog products.

Only a hex that is already stored is used. Shade names are never turned into a color.
A product with no positive price is left out, because the catalog rejects price 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.oy_catalog_repository import OyCatalogRepository
from app.schemas.catalog import Product, Shade
from app.schemas.oy_catalog import ZONE_BY_CATEGORY, OyProductInput, OyShadeInput

TEXTURES = {"matte", "velvet", "glossy", "satin", "sheer", "cream", "shimmer"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class OyCatalogBuild:
    products: list[Product] = field(default_factory=list)
    color_products: int = 0
    ar_products: int = 0
    ar_shades: int = 0
    listed_without_color: int = 0
    skipped_without_price: int = 0
    skipped_unknown_category: int = 0


def _shade_id(shade: OyShadeInput, used: set[str]) -> str:
    raw = (shade.shade_code or shade.option_id).lower()
    base = re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "shade"
    base = base[:60]
    sid, n = base, 2
    while sid in used:
        sid = f"{base[:56]}-{n}"
        n += 1
    used.add(sid)
    return sid


def _price(shades: tuple[OyShadeInput, ...]) -> int | None:
    prices = [p for shade in shades for p in (shade.sale_price, shade.list_price) if p and p > 0]
    return min(prices) if prices else None


async def load_oy_catalog(session: AsyncSession) -> OyCatalogBuild:
    return build_oy_catalog(await OyCatalogRepository(session).load_products())


def build_oy_catalog(rows: list[OyProductInput]) -> OyCatalogBuild:
    built = OyCatalogBuild(color_products=len(rows))
    for row in rows:
        mapped = ZONE_BY_CATEGORY.get(row.category_name)
        if mapped is None:
            built.skipped_unknown_category += 1
            continue
        category, zone = mapped
        price = _price(row.shades)
        if price is None:
            built.skipped_without_price += 1
            continue
        used: set[str] = set()
        shades: list[Shade] = []
        for shade in row.shades:
            hex_code = (shade.hex_code or "").upper()
            if not HEX.match(hex_code):
                continue
            name = shade.shade_name.strip() or shade.option_id
            shades.append(Shade(id=_shade_id(shade, used), name=name[:100], hex=hex_code))
        paint = zone if shades else None
        if paint:
            built.ar_products += 1
            built.ar_shades += len(shades)
        else:
            built.listed_without_color += 1
        goods = row.goods_no.strip()
        name = row.goods_name.strip() or goods
        brand = row.brand_name.strip() or "올리브영"
        built.products.append(
            Product(
                id=f"oy-{goods.lower()}"[:64],
                brand=brand[:100],
                name=name[:200],
                name_ko=name[:200],
                category=category,  # type: ignore[arg-type]
                makeup_zone=paint,  # type: ignore[arg-type]
                texture=row.texture_code if row.texture_code in TEXTURES else "satin",
                price_krw=price,
                volume=(row.volume or "")[:50],
                shades=shades,
                description="",
                key_ingredients=[],
                tags=["oliveyoung", row.category_name, *row.care_tags],
                image_url=row.image_url or "",
                search_keyword=f"{brand} {name}"[:200],
            )
        )
    return built
