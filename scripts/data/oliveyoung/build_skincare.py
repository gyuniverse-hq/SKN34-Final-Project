"""Build a read-only serving snapshot from the local DB's verified v0.3 rules.

The manifest contains only product-category/label facts. Recommendation rules,
evidence, and ingredient links are read from their normalized database tables.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "api"))
from app.schemas.skincare import SkincareSnapshot


async def build(args):
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not manifest.get("version"):
        raise ValueError("Manifest version required")
    if "ingredients" in manifest or "mappingZip" in manifest:
        raise ValueError(
            "Legacy mapping/ingredient approval fields are not accepted; "
            "validated rules and links must already be in rec_* tables"
        )
    alias_rules = (
        Path(__file__).resolve().parents[1] / "recommendation" / "ingredient_alias_rules.csv"
    )
    group_rules = (
        Path(__file__).resolve().parents[1] / "recommendation" / "ingredient_group_members.csv"
    )

    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        products = await conn.fetch(
            """SELECT p.*, b.brand_name_ko, n.volume, a.skin_types
            FROM raw_oy_product p
            LEFT JOIN raw_oy_brand b USING (brand_code)
            LEFT JOIN raw_oy_product_notice n USING (goods_no)
            LEFT JOIN raw_oy_skincare_attr a USING (goods_no)"""
        )
        options = await conn.fetch(
            """SELECT o.*, s.sale_price, s.is_sold_out
            FROM raw_oy_product_option o JOIN raw_oy_price_snapshot s USING (option_id)
            WHERE s.is_latest = true"""
        )
        option_links = await conn.fetch(
            """SELECT oi.option_id, l.ingredient_code
            FROM raw_oy_option_ingredient oi
            JOIN rec_ingredient_link l ON l.oy_ingredient_id = oi.ingredient_id"""
        )
        link_rows = await conn.fetch(
            """SELECT l.ingredient_code, l.link_method, l.linked_at
            FROM rec_ingredient_link l
            ORDER BY l.ingredient_code, l.oy_ingredient_id"""
        )
        mapping_rows = await conn.fetch(
            """SELECT mapping_id, mapping_type, target_concern, applicability_scope, runtime_enabled
            FROM rec_mapping ORDER BY mapping_id"""
        )
        component_rows = await conn.fetch(
            """SELECT mapping_id, ingredient_code, component_order
            FROM rec_mapping_ingredient ORDER BY mapping_id, component_order"""
        )
        mapping_evidence_rows = await conn.fetch(
            """SELECT mapping_id, evidence_id, supported_endpoint, study_conditions, applicability_note
            FROM rec_mapping_evidence ORDER BY mapping_id, evidence_id"""
        )
        evidence_rows = await conn.fetch(
            """SELECT DISTINCT e.evidence_id, e.pmid, e.title, e.source_url,
                   e.study_limit, e.study_type, e.publication_year
            FROM rec_evidence e JOIN rec_mapping_evidence me USING (evidence_id)
            ORDER BY e.evidence_id"""
        )
        reviews = {
            r["goods_no"]: r
            for r in await conn.fetch("SELECT * FROM raw_oy_review_summary WHERE is_latest = true")
        }
        images = await conn.fetch(
            "SELECT goods_no, image_url FROM raw_oy_image "
            "WHERE image_type='thumbnail' ORDER BY image_id"
        )
    finally:
        await conn.close()

    code_by_option = {}
    for row in option_links:
        code_by_option.setdefault(row["option_id"], set()).add(row["ingredient_code"])
    provenance = {}
    for row in link_rows:
        provenance.setdefault(row["ingredient_code"], []).append(
            {
                "linkMethod": row["link_method"],
                "linkedAt": row["linked_at"].isoformat(),
            }
        )
    components = {}
    for row in component_rows:
        components.setdefault(row["mapping_id"], []).append(row["ingredient_code"])
    map_evidence = {}
    for row in mapping_evidence_rows:
        map_evidence.setdefault(row["mapping_id"], []).append(
            {
                "evidenceId": row["evidence_id"],
                "supportedEndpoint": row["supported_endpoint"],
                "studyConditions": row["study_conditions"] or {},
                "applicabilityNote": row["applicability_note"],
            }
        )
    evidence = {
        row["evidence_id"]: {
            "evidenceId": row["evidence_id"],
            "pmid": row["pmid"],
            "title": row["title"],
            "sourceUrl": row["source_url"],
            "studyLimit": row["study_limit"],
            "studyType": row["study_type"],
            "publicationYear": row["publication_year"],
        }
        for row in evidence_rows
    }
    mappings = [
        {
            "mappingId": row["mapping_id"],
            "targetConcern": row["target_concern"],
            "mappingType": row["mapping_type"],
            "applicabilityScope": row["applicability_scope"],
            "ingredientCodes": components.get(row["mapping_id"], []),
            "evidence": map_evidence.get(row["mapping_id"], []),
            "runtimeEnabled": row["runtime_enabled"],
        }
        for row in mapping_rows
    ]

    thumbs = {row["goods_no"]: row["image_url"] for row in images}
    result = []
    skipped = {}
    for product in products:
        subcategory = manifest.get("categories", {}).get(product["std_category_code"])
        if subcategory is None:
            continue
        labels = manifest.get("labels", {}).get(product["goods_no"], {})
        review = reviews.get(product["goods_no"])
        for option in options:
            if option["goods_no"] != product["goods_no"]:
                continue
            if (
                product["delisted_at"] is not None
                or option["delisted_at"] is not None
                or product["sale_status"] not in manifest["availableSaleStatuses"]
                or option["is_sold_out"] is not False
                or not option["sale_price"]
                or not product["brand_name_ko"]
                or not product["goods_name"]
            ):
                skipped[option["option_id"]] = "unavailable_or_incomplete"
                continue
            count = review["review_count"] if review else None
            rating = review["rating_avg"] if review else None
            if not count or count < 0 or rating is None or not 1 <= rating <= 5:
                count, rating = None, None
            result.append(
                {
                    "product": {
                        "id": "oy-" + product["goods_no"].lower(),
                        "brand": product["brand_name_ko"],
                        "name": product["goods_name"],
                        "nameKo": product["goods_name"],
                        "category": "skincare",
                        "makeupZone": None,
                        "texture": None,
                        "priceKRW": option["sale_price"],
                        "volume": product["volume"] or "",
                        "shades": [],
                        "description": "",
                        "keyIngredients": [],
                        "tags": [],
                        "imageUrl": thumbs.get(product["goods_no"], ""),
                        "searchKeyword": product["goods_name"],
                    },
                    "optionId": option["option_id"],
                    "optionName": option["option_name"] or option["option_id"],
                    "sourceOptionId": option["option_id"],
                    "priceKRW": option["sale_price"],
                    "subcategory": subcategory,
                    "available": True,
                    "identityVerified": True,
                    "ingredientCodes": sorted(code_by_option.get(option["option_id"], set())),
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
            "manifestVersion": manifest["version"],
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "aliasRulesSha256": hashlib.sha256(alias_rules.read_bytes()).hexdigest(),
            "groupRulesSha256": hashlib.sha256(group_rules.read_bytes()).hexdigest(),
            "recommendationSchema": "v0.3",
        },
        "options": result,
        "evidence": evidence,
        "ingredientProvenance": provenance,
        "mappings": mappings,
    }
    snapshot = SkincareSnapshot.model_validate(payload)
    args.output.write_text(snapshot.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "options": len(result),
                "skipped": skipped,
                "mappings": len(snapshot.mappings),
                "eligibleMappings": sum(mapping.eligible() for mapping in snapshot.mappings),
                "evidenceRecords": len(snapshot.evidence),
                "ingredientCodesLinked": len(snapshot.ingredient_provenance),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    asyncio.run(build(parser.parse_args()))
