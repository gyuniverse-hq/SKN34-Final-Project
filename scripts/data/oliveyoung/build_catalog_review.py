"""Canonical, read-only Olive Young catalog review (existing data is immutable).

Requires seed/live parity. A reviewed include may append one product candidate;
unreviewed raw products are reported, never implicitly published. Legacy builders
are diagnostic only. Output is a review bundle, not a database import command.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib.util
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

MAKEUP_GROUP = {
    "립틴트": "lip",
    "립글로스": "lip",
    "립스틱": "lip",
    "립케어(컬러립밤)": "lip",
    "립케어(보습립밤)": "lip",
    "립케어(기타)": "lip",
    "립라이너": "lip",
    "블러셔": "cheek",
    "하이라이터": "cheek",
    "쉐이딩": "cheek",
    "아이섀도우": "eye",
    "아이브로우": "eye",
    "아이라이너": "eye",
    "마스카라": "eye",
    "쿠션": "base",
    "프라이머/베이스": "base",
    "파우더/팩트": "base",
    "파운데이션": "base",
    "BB/CC": "base",
    "컨실러": "base",
    "메이크업 픽서": "base",
}
CARE_CODES = set(
    [
        "로션",
        "립&아이리무버",
        "바디로션",
        "바디클렌저",
        "선블록",
        "선스틱",
        "선스프레이",
        "선쿠션",
        "선패치",
        "세트",
        "스킨/토너",
        "시트팩",
        "아이케어",
        "애프터선",
        "에센스",
        "올인원",
        "코팩",
        "크림",
        "클렌징밀크",
        "클렌징밤",
        "클렌징오일",
        "클렌징워터",
        "클렌징티슈",
        "클렌징폼",
        "태닝",
        "패드",
        "패치",
        "페이셜미스트",
        "페이셜오일",
        "페이셜팩",
        "페이셜필링&스크럽",
    ]
)
OUT_OF_SCOPE = {"키링/인형", "헤어메이크업류"}
TEXTURES = {"matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer"}
AR_ZONE_GROUP = {
    "lip": "lip",
    "blush": "cheek",
    "highlighter": "cheek",
    "contour": "cheek",
    "eyeshadow": "eye",
    "eyeliner": "eye",
    "brow": "eye",
    "mascara": "eye",
    "foundation": "base",
}


def classify(raw, override, display_group):
    """One classification policy. Preserve original classification separately."""
    source = raw["std_category_code"]
    if override is not None:
        if (
            override["sourceStandardCategory"] != source
            or override["displayCategory"] != raw["category_name"]
        ):
            raise ValueError(f"Reviewed source identity changed: {raw['goods_no']}")
        if override["decision"] == "exclude":
            return None, "reviewed_exclusion"
        if override["decision"] != "include":
            raise ValueError("Unknown reviewed decision")
        reviewed = override["reviewedCategory"]
        group = MAKEUP_GROUP.get(reviewed)
        if group is None and reviewed in CARE_CODES and display_group in ("skincare", "suncare"):
            group = display_group
        if group != override["servingCategory"] or not group:
            raise ValueError("Invalid reviewed category")
        if (
            override.get("makeupZone") is not None
            and AR_ZONE_GROUP.get(override["makeupZone"]) != group
        ):
            raise ValueError("Reviewed AR zone/category mismatch")
        return group, "reviewed_include"
    if source in OUT_OF_SCOPE:
        return None, "out_of_scope"
    if source in MAKEUP_GROUP:
        return MAKEUP_GROUP[source], "requires_review"
    if source in CARE_CODES and display_group in ("skincare", "suncare"):
        return display_group, "requires_review"
    return None, "unclassified_requires_review"


def reconcile(seed, live, raw_metadata, overrides, candidate_for, group_for):
    """Never remove or edit existing seed entries. Return append-only approved candidates."""
    from app.schemas.catalog import Product

    old = {p["id"]: p for p in seed["products"]}
    if len(old) != len(seed["products"]) or old.keys() != live.keys():
        raise ValueError("Seed/live product IDs differ")
    for pid, data in old.items():
        a, b = Product.model_validate(data), live[pid]
        aa, bb = a.model_dump(exclude={"shades"}), b.model_dump(exclude={"shades"})
        if aa != bb:
            raise ValueError(f"Seed/live product fields differ: {pid}")
        sa, sb = {s.id: s for s in a.shades}, {s.id: s for s in b.shades}
        if len(sa) != len(a.shades) or len(sb) != len(b.shades) or sa.keys() != sb.keys():
            raise ValueError(f"Seed/live shades differ: {pid}")
        for sid in sa:
            x, y = sa[sid], sb[sid]
            if x.model_dump(exclude={"color_confidence"}) != y.model_dump(
                exclude={"color_confidence"}
            ):
                raise ValueError(f"Seed/live shade differs: {pid}/{sid}")
            if x.color_confidence != y.color_confidence and (
                x.color_confidence is None
                or y.color_confidence is None
                or not math.isclose(x.color_confidence, y.color_confidence, abs_tol=1e-6)
            ):
                raise ValueError(f"Seed/live shade confidence differs: {pid}/{sid}")
    raw_ids = {r["goods_no"] for r in raw_metadata}
    if len(raw_ids) != len(raw_metadata) or not set(overrides) <= raw_ids:
        raise ValueError("Duplicate or missing reviewed raw goods")
    if not {pid for pid in old if pid.startswith("oy-")} <= {"oy-" + g.lower() for g in raw_ids}:
        raise ValueError("Existing serving OY product lacks raw identity")
    additions, report = [], []
    for raw in sorted(raw_metadata, key=lambda r: r["goods_no"]):
        gid = raw["goods_no"]
        pid = "oy-" + gid.lower()
        override = overrides.get(gid)
        group, reason = classify(raw, override, group_for(raw))
        exists = pid in old
        if bool(raw["is_in_catalog"]) != exists:
            raise ValueError(f"Raw catalog flag differs: {gid}")
        if exists:
            if reason == "reviewed_exclusion":
                raise ValueError(f"Reviewed exclusion already served: {gid}")
            if override and override["decision"] == "include":
                p = live[pid]
                if (p.category, p.texture, p.makeup_zone) != (
                    override["servingCategory"],
                    override.get("texture"),
                    override.get("makeupZone"),
                ):
                    raise ValueError(f"Reviewed product serving values differ: {gid}")
                rs = override.get("reviewedShade")
                if rs and not any(
                    s.id == rs["optionId"]
                    and s.hex == rs["hex"]
                    and s.color_source == rs["colorSource"]
                    and s.measure_method == rs["measureMethod"]
                    and s.color_confidence is not None
                    and math.isclose(s.color_confidence, rs["colorConfidence"], abs_tol=1e-6)
                    for s in p.shades
                ):
                    raise ValueError(f"Reviewed shade missing or changed: {gid}")
            decision = "preserve_existing"
        elif reason == "reviewed_include":
            if raw["delisted_at"] is not None or raw["sale_status"] != "정상":
                raise ValueError(f"Reviewed product not available: {gid}")
            additions.append(candidate_for(raw, override))
            decision = "append_reviewed_candidate"
        elif reason in ("reviewed_exclusion", "out_of_scope"):
            decision = "exclude"
        elif raw["delisted_at"] is not None or raw["sale_status"] != "정상":
            decision = "not_available"
        else:
            decision = "manual_review_required"
        report.append(
            {
                "goods_no": gid,
                "source_category": raw["std_category_code"],
                "display_category": raw["category_name"],
                "proposed_category": group,
                "policy_reason": reason,
                "decision": decision,
                "existing_served": exists,
            }
        )
    result = {**seed, "products": seed["products"] + additions}
    return result, report


async def run(args):
    repo = args.repo_root.resolve()
    sys.path.insert(0, str(repo / "backend/api"))
    from app.core.oliveyoung_image import public_oliveyoung_image_url
    from app.models.catalog import ProductRow
    from app.repositories.catalog_repository import _product
    from app.schemas.catalog import CatalogBundle, Product
    from app.schemas.oy_catalog import CARE_PATH_TOKENS
    from app.services.catalog_service import validate_catalog
    from sqlalchemy import URL, select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    spec = importlib.util.spec_from_file_location(
        "legacy_makeup_source", repo / "scripts/data/oliveyoung/build_catalog.py"
    )
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    seed = json.loads(args.seed.read_bytes())
    validate_catalog(CatalogBundle.model_validate(seed))
    rules_doc = json.loads(args.overrides.read_bytes())
    if rules_doc.get("schemaVersion") != 1:
        raise ValueError("Unknown override version")
    overrides = {p["goodsNo"]: p for p in rules_doc["products"]}
    if len(overrides) != len(rules_doc["products"]):
        raise ValueError("Duplicate reviewed product")
    password = os.environ.get("PGPASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    engine = create_async_engine(
        URL.create(
            "postgresql+asyncpg",
            username=args.user,
            password=password,
            host="127.0.0.1",
            port=args.port,
            database=args.database,
        )
    )
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            driver = (await conn.get_raw_connection()).driver_connection
            if await driver.fetchval("SHOW transaction_read_only") != "on":
                raise ValueError("Expected read-only")
            (
                raw,
                rules,
                options,
                prices,
                colors,
                textures,
                thumbs,
            ) = await legacy.fetch_source(driver)
            finishes = await legacy.fetch_finishes(driver)
            meta = [
                dict(r)
                for r in await driver.fetch(
                    """SELECT p.goods_no,p.std_category_code,p.sale_status,p.delisted_at,
                                  p.is_in_catalog,c.category_name,c.category_path
                           FROM public.raw_oy_product p
                           LEFT JOIN public.raw_oy_category c USING(category_no)"""
                )
            ]
            active = {
                r["option_id"]
                for r in await driver.fetch(
                    "SELECT option_id FROM public.raw_oy_product_option WHERE delisted_at IS NULL"
                )
            }
            available = {
                r["option_id"]
                for r in await driver.fetch(
                    "SELECT option_id FROM public.raw_oy_price_snapshot "
                    "WHERE is_latest AND is_sold_out IS FALSE AND sale_price>0"
                )
            }
            async with AsyncSession(bind=conn, join_transaction_mode="rollback_only") as session:
                live = {
                    r.id: _product(r) for r in (await session.scalars(select(ProductRow))).all()
                }
    finally:
        await engine.dispose()
    source = {r["goods_no"]: r for r in raw}
    by_goods = defaultdict(list)
    for o in options:
        if o["option_id"] in active and o["option_id"] not in legacy.CATALOG_OPTION_EXCLUSIONS:
            by_goods[o["goods_no"]].append(o)
    if set(rules) != set(MAKEUP_GROUP):
        raise ValueError("Unexpected makeup category policy change")

    def group_for(r):
        path = r["category_path"] or ""
        for token, group in CARE_PATH_TOKENS:
            if token in path:
                return "suncare" if group == "선케어" else "skincare"
        return None

    def candidate_for(r, review):
        gid = r["goods_no"]
        src = source[gid]
        code = review["reviewedCategory"]
        name, brand, volume = map(
            legacy.clean, (src["goods_name"], src["brand_name_ko"], src["volume"])
        )
        image = public_oliveyoung_image_url(thumbs.get(gid, ""))
        texture = review.get("texture")
        zone = review.get("makeupZone")
        if not all((name, brand, volume, image)) or (
            texture is not None and (texture not in TEXTURES or textures.get(gid) != texture)
        ):
            raise ValueError(f"Missing verified required data: {gid}")
        prices_for = [
            prices[o["option_id"]]["sale_price"]
            for o in by_goods[gid]
            if o["option_id"] in available
            and o["option_id"] in prices
            and prices[o["option_id"]]["sale_price"] > 0
        ]
        if not prices_for:
            raise ValueError(f"Missing available price: {gid}")
        shades = []
        missing_named = False
        for o in sorted(
            by_goods[gid],
            key=lambda o: (o["sort_seq"] is None, o["sort_seq"] or 0, o["option_id"]),
        ):
            oid = o["option_id"]
            c = colors.get(oid, {})
            hexv = (c.get("hex_code") or "").upper()
            if not legacy.HEX.fullmatch(hexv):
                if legacy.clean(o["shade_code"]) or legacy.clean(o["shade_name"]):
                    missing_named = True
                continue
            color_source = legacy.COLOR_SOURCE_BY_METHOD.get(c["color_method"])
            if not color_source:
                raise ValueError(f"Unknown color method: {oid}")
            shade = {
                "id": oid,
                "name": legacy.clean(o["shade_name"] or o["option_name"]) or oid,
                "hex": hexv,
                "measureMethod": "estimated",
                "colorSource": color_source,
                "colorConfidence": c["color_confidence"],
            }
            if oid in finishes:
                shade["finish"] = finishes[oid]
            shades.append(shade)
        rule = rules.get(code, {})
        if rule.get("requires_texture") and texture is None:
            raise ValueError("Reviewed makeup texture required")
        if rule.get("requires_color") and (missing_named or not shades):
            raise ValueError("Reviewed makeup color required")
        if zone and (texture is None or not shades):
            raise ValueError("AR needs texture and shade")
        rs = review.get("reviewedShade")
        if rs and not any(s["id"] == rs["optionId"] and s["hex"] == rs["hex"] for s in shades):
            raise ValueError("Reviewed shade not in raw evidence")
        product = Product.model_validate(
            {
                "id": "oy-" + gid.lower(),
                "brand": brand[:100],
                "name": name[:200],
                "nameKo": name[:200],
                "category": review["servingCategory"],
                "makeupZone": zone,
                "texture": texture,
                "priceKRW": min(prices_for),
                "volume": volume,
                "shades": shades,
                "description": "",
                "keyIngredients": [],
                "tags": ["oliveyoung", code],
                "imageUrl": image,
                "searchKeyword": (name if brand in name else f"{brand} {name}")[:200],
            }
        )
        return product.model_dump(mode="json", by_alias=True)

    bundle, rows = reconcile(seed, live, meta, overrides, candidate_for, group_for)
    validate_catalog(CatalogBundle.model_validate(bundle))
    if (
        bundle["products"][: len(seed["products"])] != seed["products"]
        or bundle["looks"] != seed["looks"]
        or bundle["stores"] != seed["stores"]
    ):
        raise ValueError("Existing seed changed")
    summary = {
        "seed_before": len(seed["products"]),
        "candidate_after": len(bundle["products"]),
        "raw": len(meta),
        "decisions": dict(Counter(r["decision"] for r in rows)),
        "existing_values_changed": 0,
    }
    outputs = [args.output.resolve(), args.report.resolve()]
    protected = {
        args.seed.resolve(),
        args.overrides.resolve(),
        (repo / "backend/api/seed/catalog.json").resolve(),
    }
    if len(set(outputs)) != 2 or any(p in protected or p.exists() for p in outputs):
        raise ValueError("Use fresh review output paths, never seed or override paths")
    for path, data in [
        (args.output, bundle),
        (args.report, {"summary": summary, "products": rows}),
    ]:
        with path.open("x", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))
    print("Read-only: no DB or seed writes")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    p.add_argument("--seed", type=Path, required=True)
    p.add_argument("--overrides", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--user", default="vishue")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
