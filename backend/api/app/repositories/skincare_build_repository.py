"""Build a skincare snapshot from one caller-owned PostgreSQL transaction."""

import json
import math
import re
from pathlib import Path

from app.schemas.skincare import SkincareSnapshot

SEED = Path(__file__).resolve().parents[2] / "seed" / "recommendation_v03"
IDENTITY_POLICY = (SEED / "identity.json").read_text(encoding="utf-8")
RULE_VERSION = json.loads(IDENTITY_POLICY)["version"]
BOTANICAL_COMMON_NAME = re.compile(
    r"([A-Za-z][A-Za-z-]+(?:\s+[A-Za-z][A-Za-z-]+){1,3})\s+\(([A-Za-z][A-Za-z -]{2,})\)"
)

SURVEY_CHOICES = {
    "피부타입": {"건성에 좋아요": "dry", "지성에 좋아요": "oily", "복합성에 좋아요": "combination"},
    "피부고민": {
        "보습에 좋아요": "hydrating",
        "주름/미백에 좋아요": "brighteningFirming",
        "진정에 좋아요": "soothing",
    },
    "자극도": {"자극없이 순해요": "gentle", "자극이 느껴져요": "irritating", "보통이에요": None},
}


def survey_ratios(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["goods_no"], row["question_name"]), []).append(row)
    result = {}
    for (goods, question), answers in groups.items():
        choices = SURVEY_CHOICES.get(question)
        if not choices or len(answers) != len(choices):
            continue
        if {r["answer_name"] for r in answers} != set(choices):
            continue
        values = [r["percentage"] for r in answers]
        if any(v is None or not math.isfinite(v) or not 0 <= v <= 100 for v in values):
            continue
        if abs(sum(values) - 100) > 2:
            continue
        for row in answers:
            if key := choices[row["answer_name"]]:
                result.setdefault(goods, {})[key] = row["percentage"] / 100
    return result


async def build_snapshot(conn, manifest, manifest_sha256, stats=None):
    if not manifest.get("reviewedBy") or not manifest.get("version"):
        raise ValueError("Reviewed manifest with version required")
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
    cosing_links = await conn.fetch("""SELECT oi.option_id, m.mfds_ingredient_id,
        m.oy_ingredient_id, m.match_method AS oy_match_method, m.rule_version,
        m.reviewed_by, cl.match_method AS cosing_match_method, cl.query_name,
        cl.substance_id, mf.name_en, fc.target_concern,
        array_agg(DISTINCT f.function_name ORDER BY f.function_name) AS function_names
        FROM raw_oy_option_ingredient oi
        JOIN raw_oy_product_option o ON o.option_id=oi.option_id AND o.delisted_at IS NULL
        JOIN raw_oy_price_snapshot ps ON ps.option_id=o.option_id AND ps.is_latest
            AND ps.is_sold_out IS FALSE AND ps.sale_price > 0
        JOIN raw_oy_product raw ON raw.goods_no=o.goods_no AND raw.is_in_catalog
            AND raw.delisted_at IS NULL AND raw.sale_status = ANY($1::text[])
            AND raw.std_category_code = ANY($2::text[])
        JOIN products p ON p.id='oy-' || lower(raw.goods_no) AND p.category='skincare'
        JOIN oy_mfds_ingredient_map m ON m.oy_ingredient_id=oi.ingredient_id
        JOIN raw_mfds_ingredient mf ON mf.ingredient_id=m.mfds_ingredient_id AND mf.is_current
        JOIN cosing_ingredient_lookup cl ON cl.ingredient_id=mf.ingredient_id
            AND cl.status='accepted'
        JOIN ingredient_function inf ON inf.ingredient_id=mf.ingredient_id
        JOIN cosing_function f ON f.function_id=inf.function_id
        JOIN function_concern fc ON fc.function_id=f.function_id
        GROUP BY oi.option_id, m.mfds_ingredient_id, m.oy_ingredient_id, m.match_method,
        m.rule_version, m.reviewed_by, cl.match_method, cl.query_name,
        cl.substance_id, mf.name_en, fc.target_concern""",
        manifest["availableSaleStatuses"], list(manifest["categories"]))
    reviews = {
        r["goods_no"]: r
        for r in await conn.fetch("SELECT * FROM raw_oy_review_summary WHERE is_latest = true")
    }
    surveys = survey_ratios(
        await conn.fetch("""
        SELECT s.goods_no, q.question_name, a.answer_name, s.percentage
        FROM raw_oy_review_survey s
        JOIN raw_oy_review_summary r ON r.goods_no=s.goods_no
             AND r.is_latest AND r.collected_at=s.collected_at
        JOIN raw_oy_survey_answer a USING(answer_code)
        JOIN raw_oy_survey_question q USING(question_code)
        WHERE q.question_name IN ('피부타입','피부고민','자극도')
    """)
    )
    provenance = {}
    option_codes = {}
    option_matches = {}
    cosing_mappings = {}
    cosing_provenance = {}
    for row in cosing_links:
        original = (row["name_en"] or "").strip()
        query = original.upper()
        if row["cosing_match_method"] == "normalized":
            query = BOTANICAL_COMMON_NAME.sub(r"\1", original).upper()
        if not original or query != row["query_name"] or not row["substance_id"]:
            continue
        ingredient_id = row["mfds_ingredient_id"]
        code = f"cosing:mfds:{ingredient_id}"
        mapping_id = f"cosing:{ingredient_id}:{row['target_concern']}"
        if code in provenance:
            raise ValueError("CosIng ingredient code conflicts with existing recommendation data")
        cosing_provenance.setdefault(code, set()).add(
            f"cosing:mfds:{ingredient_id}:{row['cosing_match_method']}:"
            f"oy:{row['oy_ingredient_id']}:{row['oy_match_method']}:"
            f"{row['rule_version'] or row['reviewed_by']}"
        )
        if mapping_id not in cosing_mappings:
            cosing_mappings[mapping_id] = {
                "mappingId": mapping_id,
                "targetConcern": row["target_concern"],
                "ingredientCodes": [code],
                "functionNames": set(),
                "substanceId": row["substance_id"],
                "matchMethod": row["cosing_match_method"],
            }
        cosing_mappings[mapping_id]["functionNames"].update(row["function_names"])
        option_codes.setdefault(row["option_id"], set()).add(code)
        option_matches.setdefault(row["option_id"], set()).add(mapping_id)
    provenance.update({
        code: {"source": "|".join(sorted(sources)), "ruleVersion": "cosing-ingredient-functions-v1"}
        for code, sources in cosing_provenance.items()
    })
    options_by_goods = {}
    for option in options:
        options_by_goods.setdefault(option["goods_no"], []).append(option)
    result = []
    skipped = {}
    for p in products:
        sub = manifest["categories"].get(p["std_category_code"])
        if sub is None:
            continue
        product = json.loads(p["catalog_product"])
        labels = manifest.get("labels", {}).get(p["goods_no"], {})
        review = reviews.get(p["goods_no"])
        for o in options_by_goods.get(p["goods_no"], []):
            if (
                p["delisted_at"] is not None
                or o["delisted_at"] is not None
                or p["sale_status"] not in manifest["availableSaleStatuses"]
                or o["is_sold_out"] is not False
                or not o["sale_price"]
                or o["sale_price"] <= 0
                or not product["brand"]
                or not product["name"]
            ):
                skipped[o["option_id"]] = "unavailable_or_incomplete"
                continue
            pattern = manifest.get("excludedNamePattern")
            if pattern and (
                re.search(pattern, product["name"], re.IGNORECASE)
                or re.search(pattern, o["option_name"] or "", re.IGNORECASE)
            ):
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
                    "surveyRatios": surveys.get(p["goods_no"], {}) if count else {},
                }
            )
    payload = {
        "dataVersion": manifest["version"],
        "sourceManifest": {
            "reviewedBy": manifest["reviewedBy"],
            "mappingSource": "cosing_function+function_concern",
            "mappingPolicy": "cosing-only-v1",
            "schemaVersion": "0.3",
            "identityVersion": "cosing-ingredient-functions-v1",
            "ingredientSource": "oy_mfds_ingredient_map+ingredient_function",
            "cosingSource": (
                "oy_mfds_ingredient_map+raw_mfds_ingredient+cosing_ingredient_lookup+"
                "ingredient_function+cosing_function+function_concern"
            ),
            "manifestSha256": manifest_sha256,
        },
        "options": sorted(result, key=lambda option: option["optionId"]),
        "evidence": {},
        "ingredientProvenance": provenance,
        "mappings": [
            {**mapping, "functionNames": sorted(mapping["functionNames"])}
            for _, mapping in sorted(cosing_mappings.items())
        ],
    }
    snapshot = SkincareSnapshot.model_validate(payload)
    if stats is not None:
        stats.update(
            unlinkedCodes=[],
            options=len(result),
            skipped=skipped,
            activeMappings=sum(m.eligible() for m in snapshot.mappings),
        )
    return snapshot
