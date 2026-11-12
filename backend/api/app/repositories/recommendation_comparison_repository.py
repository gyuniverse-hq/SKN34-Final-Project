"""Read-only adapter for the explicitly versioned COSING serving projection."""

import hashlib
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.recommendation_comparison import (
    CandidateOption,
    ComparisonCatalog,
    ReviewEvidence,
)


class ComparisonRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read(self) -> ComparisonCatalog:
        async with self.session.begin():
            await self.session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            await self.session.execute(text("SET LOCAL statement_timeout = '30s'"))
            payload = (
                await self.session.execute(text("SELECT payload FROM skincare_serving WHERE id=1"))
            ).scalar_one()
            if isinstance(payload, str):
                payload = json.loads(payload)
            manifest = payload.get("sourceManifest", {})
            if (
                manifest.get("schemaVersion") != "0.3"
                or manifest.get("mappingPolicy") != "cosing-only-v1"
            ):
                raise ValueError("unsupported_cosing_snapshot")
            options = [
                o for o in payload["options"] if o.get("available") and o.get("identityVerified")
            ]
            if any(o["optionId"] != o["sourceOptionId"] for o in options):
                raise ValueError("invalid_option_lineage")
            records = (
                (
                    await self.session.execute(
                        text("""
                SELECT oi.option_id::text AS option_id, m.mfds_ingredient_id
                FROM raw_oy_option_ingredient oi JOIN oy_mfds_ingredient_map m
                  ON m.oy_ingredient_id = oi.ingredient_id
                WHERE oi.option_id::text = ANY(:ids)
            """),
                        {"ids": [o["optionId"] for o in options]},
                    )
                )
                .mappings()
                .all()
            )
            ids: dict[str, set[int]] = {}
            for row in records:
                ids.setdefault(row["option_id"], set()).add(row["mfds_ingredient_id"])
            names = dict(
                (
                    await self.session.execute(
                        text("SELECT ingredient_id, name_ko FROM raw_mfds_ingredient")
                    )
                ).all()
            )
            # Original ingredient/tag associations are independent of the serving projection.
            function_rows = (
                await self.session.execute(
                    text("""
                SELECT i.ingredient_id, f.function_name
                FROM ingredient_function i
                JOIN cosing_function f USING(function_id)
                ORDER BY i.ingredient_id, f.function_name
            """)
                )
            ).all()
            functions: dict[int, list[str]] = {}
            for ingredient_id, function_name in function_rows:
                functions.setdefault(ingredient_id, []).append(function_name)
            concern_rows = (
                await self.session.execute(
                    text("""
                SELECT c.target_concern, f.function_name
                FROM function_concern c JOIN cosing_function f USING(function_id)
                ORDER BY c.target_concern, f.function_name
            """)
                )
            ).all()
            functions_by_concern: dict[str, list[str]] = {}
            for concern, function_name in concern_rows:
                functions_by_concern.setdefault(concern, []).append(function_name)
            # Reuse V1's published survey inputs, including its combined outcome signal.
            rating_rows = (
                (
                    await self.session.execute(
                        text("""
                    SELECT 'oy-' || lower(goods_no) AS product_id, review_count, rating_avg,
                           rating_1_pct, rating_2_pct, rating_3_pct, rating_4_pct, rating_5_pct
                    FROM raw_oy_review_summary
                    WHERE is_latest AND 'oy-' || lower(goods_no) = ANY(:ids)
                """),
                        {"ids": sorted({o["product"]["id"] for o in options})},
                    )
                )
                .mappings()
                .all()
            )
            rating_sources = {}
            for row in rating_rows:
                if row["product_id"] in rating_sources:
                    raise ValueError("duplicate_latest_rating_distribution")
                rating_sources[row["product_id"]] = dict(row)

            def rating_evidence(option):
                source = rating_sources.get(option["product"]["id"])
                if source is None:
                    return {"rating_distribution_status": "missing"}
                if source["review_count"] and (
                    (source["rating_avg"] is None) != (option.get("ratingAvg") is None)
                ):
                    return {"rating_distribution_status": "snapshot_mismatch"}
                if (source["review_count"] or 0) != (option.get("reviewCount") or 0) or (
                    source["rating_avg"] is not None
                    and option.get("ratingAvg") is not None
                    and abs(float(source["rating_avg"]) - option["ratingAvg"]) > 1e-6
                ):
                    return {"rating_distribution_status": "snapshot_mismatch"}
                return {
                    "rating_distribution_status": "matched",
                    "rating_percentages": tuple(source[f"rating_{s}_pct"] for s in range(1, 6)),
                }

            candidates = [
                CandidateOption(
                    product_id=o["product"]["id"],
                    product_name=o["product"].get("nameKo") or o["product"]["name"],
                    option_id=o["optionId"],
                    ingredient_ids=sorted(ids.get(o["optionId"], set())),
                    subcategory=o.get("subcategory"),
                    skin_types=o.get("skinTypes") or [],
                    label_source=o.get("labelSource"),
                    review=ReviewEvidence(
                        survey_ratios=o.get("surveyRatios") or {},
                        review_count=o.get("reviewCount"),
                        rating_avg=o.get("ratingAvg"),
                        **rating_evidence(o),
                    ),
                )
                for o in options
            ]
            audit = {
                "snapshot": payload,
                "optionIngredients": {key: sorted(value) for key, value in sorted(ids.items())},
                "cosingFunctions": functions,
                "concernFunctions": functions_by_concern,
                "ratingDistributions": {
                    o.product_id: o.review.model_dump(
                        include={"rating_percentages", "rating_distribution_status"}
                    )
                    for o in candidates
                },
            }
            digest = hashlib.sha256(
                json.dumps(audit, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            return ComparisonCatalog(
                version=payload["dataVersion"],
                digest=digest,
                options=candidates,
                names=names,
                source_manifest=manifest,
                functions_by_id=functions,
                functions_by_concern=functions_by_concern,
            )
