"""Read-only build from DB rec_* mappings + raw rows + reviewed category manifest.
Run in backend/api's uv environment. Writes only the specified reviewable JSON file.
Never activates mappings or changes ingredient links. DB matches remain option-specific.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "api"))
from app.core.config import Settings
from app.schemas.skincare import SkincareSnapshot


async def build(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not manifest.get("reviewedBy") or not manifest.get("version"):
        raise ValueError("Reviewed manifest with version required")
    conn = await asyncpg.connect(
        Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        # One consistent, read-only view of mapping approvals, links and raw options.
        await conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        mappings = await conn.fetch("SELECT * FROM rec_mapping ORDER BY mapping_id")
        evidence = await conn.fetch("SELECT * FROM rec_evidence ORDER BY evidence_id")
        components = await conn.fetch("""SELECT mapping_id, ingredient_code
            FROM rec_mapping_ingredient ORDER BY mapping_id, component_order, ingredient_code""")
        links = await conn.fetch("""SELECT ingredient_code, oy_ingredient_id, link_method,
            reviewed_by, reviewed_at FROM rec_ingredient_link
            ORDER BY ingredient_code, oy_ingredient_id""")
        matches = await conn.fetch("SELECT mapping_id, option_id FROM rec_concern_match")
        products = await conn.fetch("""SELECT raw.goods_no, raw.std_category_code,
            raw.sale_status, raw.delisted_at,
            to_jsonb(c) || jsonb_build_object('shades', COALESCE((
                SELECT jsonb_agg(to_jsonb(s) ORDER BY s.position, s.id)
                FROM shades s WHERE s.product_id = c.id
            ), '[]'::jsonb)) AS catalog_product
            FROM products c
            JOIN raw_oy_product raw ON c.id = 'oy-' || lower(raw.goods_no)
            WHERE c.category = 'skincare' AND raw.is_in_catalog""")
        options = await conn.fetch("""SELECT o.*, s.sale_price, s.is_sold_out
            FROM raw_oy_product_option o JOIN raw_oy_price_snapshot s USING (option_id)
            WHERE s.is_latest = true""")
        ingredients = await conn.fetch("""SELECT oi.option_id, l.ingredient_code
            FROM raw_oy_option_ingredient oi
            JOIN rec_ingredient_link l ON l.oy_ingredient_id=oi.ingredient_id""")
        reviews = {
            r["goods_no"]: r
            for r in await conn.fetch("SELECT * FROM raw_oy_review_summary WHERE is_latest = true")
        }
    finally:
        await conn.close()
    mapping_codes = {}
    for row in components:
        mapping_codes.setdefault(row["mapping_id"], []).append(row["ingredient_code"])
    # A normalized component list is required; never fall back to the raw text column.
    if any(not mapping_codes.get(m["mapping_id"]) for m in mappings):
        raise ValueError("DB mapping has no normalized ingredient components")
    provenance = {}
    for row in links:
        if row["link_method"] != "exact_name" and (
            not row["reviewed_by"] or not row["reviewed_at"]
        ):
            raise ValueError("DB ingredient link is missing manual review provenance")
        if row["link_method"] not in ("exact_name", "manual", "group_member"):
            raise ValueError("Unsupported DB ingredient link method")
        entry = provenance.setdefault(row["ingredient_code"], {"source": [], "reviewedBy": []})
        entry["source"].append(
            f"rec_ingredient_link:{row['oy_ingredient_id']}:{row['link_method']}"
        )
        entry["reviewedBy"].append(row["reviewed_by"] or "db:exact_name")
    provenance = {
        code: {key: "|".join(sorted(set(values))) for key, values in entry.items()}
        for code, entry in provenance.items()
    }
    option_codes = {}
    for row in ingredients:
        option_codes.setdefault(row["option_id"], set()).add(row["ingredient_code"])
    option_matches = {}
    for row in matches:
        option_matches.setdefault(row["option_id"], set()).add(row["mapping_id"])
    result = []
    skipped = {}
    for p in products:
        sub = manifest["categories"].get(p["std_category_code"])
        if sub is None:
            continue
        product = json.loads(p["catalog_product"])
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
                or not product["brand"]
                or not product["name"]
            ):
                skipped[o["option_id"]] = "unavailable_or_incomplete"
                continue
            count = review["review_count"] if review else None
            rating = review["rating_avg"] if review else None
            if not count or count < 0 or rating is None or not 1 <= rating <= 5:
                count, rating = None, None
            result.append(
                {
                    "product": product,
                    "optionId": o["option_id"],
                    "optionName": o["option_name"] or o["option_id"],
                    "sourceOptionId": o["option_id"],
                    "priceKRW": o["sale_price"],
                    "subcategory": sub,
                    "available": True,
                    "identityVerified": True,
                    "ingredientCodes": sorted(option_codes.get(o["option_id"], set())),
                    "matchedMappingIds": sorted(option_matches.get(o["option_id"], set())),
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
            "mappingSource": "rec_mapping+rec_mapping_ingredient+rec_concern_match",
            "ingredientSource": "rec_ingredient_link",
            "manifestSha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        },
        "options": result,
        "evidence": {
            r["evidence_id"]: {k: str(v) for k, v in dict(r).items() if v is not None}
            for r in evidence
        },
        "ingredientProvenance": provenance,
        "mappings": [
            {
                "mappingId": m["mapping_id"],
                "targetConcern": m["target_concern"],
                "mappingType": m["mapping_type"],
                "ingredientCodes": mapping_codes[m["mapping_id"]],
                "evidenceIds": [m["evidence_id"]] if m["evidence_id"] else [],
                "mappingStatus": m["mapping_status"],
                "humanMappingReview": m["human_mapping_review"] or "",
                "aiPaperReview": m["ai_paper_review"] or "",
                "reReviewRequired": m["re_review_required"],
                "runtimeEnabled": m["runtime_enabled"],
                "identityVerified": all(c in provenance for c in mapping_codes[m["mapping_id"]]),
            }
            for m in mappings
        ],
    }
    snapshot = SkincareSnapshot.model_validate(payload)
    args.output.write_text(snapshot.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "unlinkedCodes": sorted(
                    {c for m in mappings for c in mapping_codes[m["mapping_id"]]} - set(provenance)
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
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    asyncio.run(build(parser.parse_args()))
