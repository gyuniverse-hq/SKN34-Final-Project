"""Read-only build from DB raw rows + reviewed identity/category manifest + mapping ZIP.
Run in backend/api's uv environment. Writes only the specified reviewable JSON file.
Never joins ZIP ingredient integers with operational IDs or activates a mapping.
"""

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "api"))
from app.schemas.skincare import SkincareSnapshot


async def build(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest.get("reviewedBy") or not manifest.get("version"):
        raise ValueError("Reviewed manifest with version required")
    with zipfile.ZipFile(args.mapping_zip) as archive:

        def rows(name):
            return list(
                csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig")))
            )

        mappings = rows("recommendation_mapping.csv")
        evidence = rows("evidence_sources.csv")
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        products = await conn.fetch("""SELECT p.*, b.brand_name_ko, n.volume,
            a.skin_types FROM raw_oy_product p
            LEFT JOIN raw_oy_brand b USING (brand_code)
            LEFT JOIN raw_oy_product_notice n USING (goods_no)
            LEFT JOIN raw_oy_skincare_attr a USING (goods_no)""")
        options = await conn.fetch("""SELECT o.*, s.sale_price, s.is_sold_out
            FROM raw_oy_product_option o JOIN raw_oy_price_snapshot s USING (option_id)
            WHERE s.is_latest = true""")
        ingredients = await conn.fetch("""SELECT oi.option_id, m.mfds_ingredient_id
            FROM raw_oy_option_ingredient oi
            JOIN oy_mfds_ingredient_map m ON m.oy_ingredient_id=oi.ingredient_id""")
        reviews = {
            r["goods_no"]: r
            for r in await conn.fetch(
                "SELECT * FROM raw_oy_review_summary WHERE is_latest = true"
            )
        }
        images = await conn.fetch(
            "SELECT goods_no, image_url FROM raw_oy_image WHERE image_type='thumbnail' ORDER BY image_id"
        )
    finally:
        await conn.close()
    # Explicit reviewed MFDS IDs; source CSV integers are never used here.
    identities = manifest["ingredients"]
    code_ids = {
        c: set(v["mfdsIds"])
        for c, v in identities.items()
        if v.get("reviewedBy") and v.get("source")
    }
    option_codes = {}
    for r in ingredients:
        for code, ids in code_ids.items():
            if r["mfds_ingredient_id"] in ids:
                option_codes.setdefault(r["option_id"], set()).add(code)
    thumbs = {r["goods_no"]: r["image_url"] for r in images}
    result = []
    skipped = {}
    for p in products:
        sub = manifest["categories"].get(p["std_category_code"])
        if sub is None:
            continue
        labels = manifest.get("labels", {}).get(p["goods_no"], {})
        review = reviews.get(p["goods_no"])
        for o in options:
            if o["goods_no"] != p["goods_no"]:
                continue
            if (
                p["delisted_at"] is not None
                or o["delisted_at"] is not None
                or p["sale_status"] not in manifest["availableSaleStatuses"]
                or o["is_sold_out"] is not False
                or not o["sale_price"]
                or not p["brand_name_ko"]
                or not p["goods_name"]
            ):
                skipped[o["option_id"]] = "unavailable_or_incomplete"
                continue
            count = review["review_count"] if review else None
            rating = review["rating_avg"] if review else None
            if not count or count < 0 or rating is None or not 1 <= rating <= 5:
                count, rating = None, None
            result.append(
                {
                    "product": {
                        "id": "oy-" + p["goods_no"].lower(),
                        "brand": p["brand_name_ko"],
                        "name": p["goods_name"],
                        "nameKo": p["goods_name"],
                        "category": "skincare",
                        "makeupZone": None,
                        "texture": None,
                        "priceKRW": o["sale_price"],
                        "volume": p["volume"] or "",
                        "shades": [],
                        "description": "",
                        "keyIngredients": [],
                        "tags": [],
                        "imageUrl": thumbs.get(p["goods_no"], ""),
                        "searchKeyword": p["goods_name"],
                    },
                    "optionId": o["option_id"],
                    "optionName": o["option_name"] or o["option_id"],
                    "sourceOptionId": o["option_id"],
                    "priceKRW": o["sale_price"],
                    "subcategory": sub,
                    "available": True,
                    "identityVerified": True,
                    "ingredientCodes": sorted(option_codes.get(o["option_id"], set())),
                    "skinTypes": labels.get("skinTypes", []),
                    "sensitiveLabel": labels.get("sensitive", False),
                    "labelSource": labels.get("source"),
                    "reviewCount": count,
                    "ratingAvg": rating,
                }
            )
    payload = {
        "dataVersion": manifest["version"],
        "sourceManifest": {
            "reviewedBy": manifest["reviewedBy"],
            "mappingZip": args.mapping_zip.name,
            "mappingSha256": hashlib.sha256(args.mapping_zip.read_bytes()).hexdigest(),
            "manifestSha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        },
        "options": result,
        "evidence": {r["evidence_id"]: r for r in evidence},
        "ingredientProvenance": {
            c: {
                "source": identities[c]["source"],
                "reviewedBy": identities[c]["reviewedBy"],
            }
            for c in code_ids
        },
        "mappings": [
            {
                "mappingId": m["mapping_id"],
                "targetConcern": m["target_concern"],
                "mappingType": m["mapping_type"],
                "ingredientCodes": m["ingredient_codes"].split("|"),
                "evidenceIds": m["evidence_id"].split("|"),
                "mappingStatus": m["mapping_status"],
                "humanMappingReview": m["human_mapping_review"],
                "aiPaperReview": m["ai_paper_review"],
                "reReviewRequired": m["re_review_required"] == "1",
                "runtimeEnabled": m["runtime_enabled"] == "1",
                "identityVerified": all(
                    c in code_ids for c in m["ingredient_codes"].split("|")
                ),
            }
            for m in mappings
        ],
    }
    snapshot = SkincareSnapshot.model_validate(payload)
    args.output.write_text(
        snapshot.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "unlinkedCodes": sorted(
                    {c for m in mappings for c in m["ingredient_codes"].split("|")}
                    - set(code_ids)
                ),
                "options": len(result),
                "skipped": skipped,
                "activeMappings": sum(m.eligible() for m in snapshot.mappings),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mapping_zip", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    asyncio.run(build(parser.parse_args()))
