"""SELECT-only ingredient access. Slug candidates and client option IDs are never authority."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.catalog import ProductRow, ShadeRow
from app.models.raw_oliveyoung import (
    RawOyIngredientRow,
    RawOyOptionIngredientRow,
    RawOyProductNoticeRow,
    RawOyProductOptionRow,
    RawOyProductRow,
)
from app.schemas.ingredient import (
    IngredientEntry,
    IngredientEvidence,
    IngredientMapping,
    IngredientReadResult,
)


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def catalog_fingerprint(product_id, zone, texture, shades) -> str:
    return fingerprint([product_id, zone, texture, [list(s) for s in shades]])


class IngredientRepository:
    def __init__(
        self,
        session: AsyncSession,
        mappings: list[IngredientMapping] | None = None,
        *,
        mapping_path: str | Path | None = None,
    ):
        self._session = session
        self._mappings = mappings
        # An explicit artifact avoids dependency on checkout layout, CWD or Docker image depth.
        self._mapping_path = (
            mapping_path if mapping_path is not None else Settings().ingredient_mapping_path
        )

    async def _rows(self, statement):
        result = await self._session.execute(statement.execution_options(autoflush=False))
        return result.all()

    def _mapping(self, product_id, shade_id):
        records = self._mappings
        if records is None:
            if not self._mapping_path or not str(self._mapping_path).strip():
                raise ApiError(
                    503,
                    "Ingredient mapping path is not configured",
                    "ingredient_mapping_not_configured",
                )
            path = Path(self._mapping_path)
            if not path.is_absolute():
                raise ApiError(
                    503,
                    "Ingredient mapping path must be absolute",
                    "ingredient_mapping_path_invalid",
                )
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(report, dict):
                    raise ValueError("Invalid artifact envelope")
                version = report.get("schemaVersion")
                if type(version) is not int or version != 1:
                    raise ApiError(
                        503,
                        "Unsupported ingredient mapping version",
                        "ingredient_mapping_version_unsupported",
                    )
                if not isinstance(report["records"], list):
                    raise ValueError("Invalid artifact records")
                records = [IngredientMapping.model_validate(r) for r in report["records"]]
            except FileNotFoundError as exc:
                raise ApiError(
                    503, "Ingredient mapping file is missing", "ingredient_mapping_missing"
                ) from exc
            except OSError as exc:
                raise ApiError(
                    503, "Ingredient mapping file is unavailable", "ingredient_mapping_unavailable"
                ) from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise ApiError(
                    503, "Ingredient mapping file is invalid", "ingredient_mapping_invalid"
                ) from exc
        matches = [r for r in records if r.product_id == product_id and r.shade_id == shade_id]
        if len(matches) > 1:
            raise ApiError(
                503, "Duplicate ingredient mapping records", "ingredient_mapping_invalid"
            )
        return matches[0] if len(matches) == 1 else None

    async def lookup(
        self, product_id: str, shade_id: str | None, option_id: str | None = None
    ) -> IngredientReadResult:
        products = await self._rows(
            select(ProductRow.id, ProductRow.makeup_zone, ProductRow.texture).where(
                ProductRow.id == product_id
            )
        )
        if not products:
            raise ApiError(404, "Product not found", "not_found")
        _, zone, texture = products[0]
        shades = await self._rows(
            select(ShadeRow.id, ShadeRow.name, ShadeRow.hex)
            .where(ShadeRow.product_id == product_id)
            .order_by(ShadeRow.position, ShadeRow.id)
        )
        response = IngredientReadResult(
            product_id=product_id, shade_id=shade_id, reason="shade_required"
        )
        if shade_id is None:
            return response
        if shade_id not in {s[0] for s in shades}:
            raise ApiError(404, "Shade not found", "shade_not_found")
        mapping = self._mapping(product_id, shade_id)
        if mapping is None:
            response.reason = "mapping_not_available"
            return response
        response.mapping_status = mapping.mapping_status
        response.source_fingerprint = mapping.source_fingerprint
        response.generator_version = mapping.generator_version
        response.synthetic = mapping.synthetic
        if mapping.catalog_fingerprint != catalog_fingerprint(product_id, zone, texture, shades):
            response.mapping_status = "mismatch"
            response.reason = "catalog_version_mismatch"
            return response
        if mapping.mapping_status != "reproduced":
            response.reason = "mapping_not_verified"
            return response
        if (
            not mapping.source_fingerprint
            or not mapping.generation_record_id
            or not mapping.generator_version
            or mapping.mapping_method != "generator_replay"
        ):
            response.mapping_status = "mismatch"
            response.reason = "replay_provenance_incomplete"
            return response
        if not mapping.option_id or (option_id is not None and option_id != mapping.option_id):
            response.reason = "option_mismatch"
            return response
        raw = await self._rows(
            select(
                RawOyProductOptionRow.option_id,
                RawOyProductOptionRow.goods_no,
                RawOyProductOptionRow.shade_code,
                RawOyProductOptionRow.option_name,
                RawOyProductOptionRow.shade_name,
                RawOyProductOptionRow.collected_at,
                RawOyProductOptionRow.delisted_at,
                RawOyProductRow.product_url,
                RawOyProductNoticeRow.ingredients_raw,
                RawOyProductNoticeRow.collected_at,
                RawOyProductRow.delisted_at,
            )
            .join(RawOyProductRow, RawOyProductRow.goods_no == RawOyProductOptionRow.goods_no)
            .outerjoin(
                RawOyProductNoticeRow, RawOyProductNoticeRow.goods_no == RawOyProductRow.goods_no
            )
            .where(RawOyProductOptionRow.option_id == mapping.option_id)
        )
        if (
            not raw
            or not mapping.goods_no
            or raw[0][1] != mapping.goods_no
            or product_id != "oy-" + mapping.goods_no.lower()
            or raw[0][6] is not None
            or raw[0][10] is not None
        ):
            response.mapping_status = "mismatch"
            response.reason = "option_ownership_or_source_mismatch"
            return response
        if not raw[0][8] or not raw[0][8].strip():
            response.reason = "ingredients_raw_unavailable"
            return response
        rows = await self._rows(
            select(
                RawOyOptionIngredientRow.ingredient_id,
                RawOyIngredientRow.ingredient_name,
                RawOyOptionIngredientRow.seq,
            )
            .outerjoin(
                RawOyIngredientRow,
                RawOyIngredientRow.ingredient_id == RawOyOptionIngredientRow.ingredient_id,
            )
            .where(RawOyOptionIngredientRow.option_id == mapping.option_id)
            .order_by(RawOyOptionIngredientRow.seq, RawOyOptionIngredientRow.ingredient_id)
        )
        version = fingerprint([list(raw[0]), [list(row) for row in rows]])
        response.source_version = version
        if mapping.source_version != version:
            response.mapping_status = "mismatch"
            response.reason = (
                "source_version_unverified"
                if not mapping.source_version
                else "source_version_mismatch"
            )
            return response
        stamp = raw[0][9]
        response.option_id = mapping.option_id
        response.collected_at_raw = stamp.isoformat() if stamp else None
        aware = (
            stamp if stamp and stamp.tzinfo is not None and stamp.utcoffset() is not None else None
        )
        if stamp and aware is None:
            response.issues.append("source_timezone_unknown")
        valid_names = all(row[1] and row[1].strip() for row in rows)
        sequences = [row[2] for row in rows]
        if not valid_names or None in sequences or sequences != list(range(1, len(sequences) + 1)):
            response.issues.append("ingredient_list_inconsistent")
        response.reason = "evidence_not_reviewed"
        if mapping.review_status != "verified":
            return response
        entries = [
            IngredientEntry(name=row[1], sequence=row[2])
            for row in rows
            if row[1] and (row[2] is None or row[2] > 0)
        ]
        evidence = IngredientEvidence(
            product_id=product_id,
            shade_id=shade_id,
            option_id=mapping.option_id,
            evidence_id="ingredient:" + fingerprint([product_id, shade_id, version]),
            ingredients=entries,
            source="option_ingredients",
            source_ref=raw[0][7],
            collected_at=aware,
            mapping_status="verified",
            review_status=mapping.review_status,
            ingredient_coverage=mapping.ingredient_coverage,
            normalization_status=mapping.normalization_status,
            synthetic=mapping.synthetic,
        )
        if "ingredient_list_inconsistent" in response.issues:
            evidence.ingredient_coverage = "partial"
            evidence.normalization_status = "unverified"
        response.evidence = evidence
        response.reason = "verified_evidence" if not response.issues else "evidence_requires_review"
        return response
