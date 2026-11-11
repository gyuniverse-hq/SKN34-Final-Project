"""Read option observations and verify version-bound ingredient evidence."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
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
from app.repositories.ingredient_identity_repository import IngredientIdentityRepository
from app.schemas.catalog_options import (
    DisplayedIngredient,
    ObservedOptionLabel,
    OptionIngredientInformation,
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


def _option_source():
    # Keep the column order for the source fingerprint used by schemaVersion 1 artifacts.
    return (
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
    )


def _ingredient_rows():
    return (
        select(
            RawOyOptionIngredientRow.ingredient_id,
            RawOyIngredientRow.ingredient_name,
            RawOyOptionIngredientRow.seq,
        )
        .outerjoin(
            RawOyIngredientRow,
            RawOyIngredientRow.ingredient_id == RawOyOptionIngredientRow.ingredient_id,
        )
        .order_by(RawOyOptionIngredientRow.seq, RawOyOptionIngredientRow.ingredient_id)
    )


def _validate_mapping(result, mapping, zone, texture, shades, requested_option) -> bool:
    result.mapping_status = mapping.mapping_status
    result.source_fingerprint = mapping.source_fingerprint
    result.generator_version = mapping.generator_version
    result.synthetic = mapping.synthetic
    if mapping.catalog_fingerprint != catalog_fingerprint(result.product_id, zone, texture, shades):
        result.mapping_status = "mismatch"
        result.reason = "catalog_version_mismatch"
        return False
    direct = mapping.mapping_status == "directly_reviewed"
    if not direct and mapping.mapping_status != "reproduced":
        result.reason = "mapping_not_verified"
        return False
    if direct and (
        mapping.mapping_method != "direct_review"
        or not mapping.reviewed_by
        or not mapping.reviewed_at
        or not mapping.review_ref
    ):
        result.reason = "direct_review_incomplete"
        return False
    if not direct and (
        not mapping.source_fingerprint
        or not mapping.generation_record_id
        or not mapping.generator_version
        or mapping.mapping_method != "generator_replay"
    ):
        result.mapping_status = "mismatch"
        result.reason = "replay_provenance_incomplete"
        return False
    if not mapping.option_id or (
        requested_option is not None and requested_option != mapping.option_id
    ):
        result.reason = "option_mismatch"
        return False
    return True


def _owns_option(product_id, raw) -> bool:
    return bool(
        raw
        and raw[1]
        and product_id == "oy-" + raw[1].lower()
        and raw[6] is None
        and raw[10] is None
    )


def _validate_source(result, mapping, raw) -> bool:
    if not _owns_option(result.product_id, raw) or raw[1] != mapping.goods_no:
        result.mapping_status = "mismatch"
        result.reason = "option_ownership_or_source_mismatch"
        return False
    if not raw[8] or not raw[8].strip():
        result.reason = "ingredients_raw_unavailable"
        return False
    return True


def _source_version(raw, rows) -> str:
    return fingerprint([list(raw), [list(row) for row in rows]])


def _prepare_evidence(result, mapping, raw, rows, version) -> None:
    result.source_version = version
    if mapping.source_version != version:
        result.mapping_status = "mismatch"
        result.reason = (
            "source_version_unverified" if not mapping.source_version else "source_version_mismatch"
        )
        return
    stamp = raw[9]
    result.option_id = mapping.option_id
    result.collected_at_raw = stamp.isoformat() if stamp else None
    aware = stamp if stamp and stamp.utcoffset() is not None else None
    if stamp and aware is None:
        result.issues.append("source_timezone_unknown")
    valid_names = all(row[1] and row[1].strip() for row in rows)
    sequences = [row[2] for row in rows]
    if not valid_names or sequences != list(range(1, len(sequences) + 1)):
        result.issues.append("ingredient_list_inconsistent")
    result.reason = "evidence_not_reviewed"
    if mapping.review_status != "verified":
        return

    direct = mapping.mapping_status == "directly_reviewed"
    result.evidence = IngredientEvidence(
        product_id=result.product_id,
        shade_id=result.shade_id,
        option_id=mapping.option_id,
        evidence_id="ingredient:" + fingerprint([result.product_id, result.shade_id, version]),
        source="option_ingredients",
        source_ref=raw[7],
        collected_at=aware,
        reviewed_at=mapping.reviewed_at if direct else None,
        review_ref=mapping.review_ref if direct else None,
        mapping_status="verified",
        review_status=mapping.review_status,
        ingredient_coverage=mapping.ingredient_coverage,
        normalization_status=mapping.normalization_status,
        synthetic=mapping.synthetic,
    )
    if "ingredient_list_inconsistent" in result.issues:
        result.evidence.ingredient_coverage = "partial"
        result.evidence.normalization_status = "unverified"
    warnings = {"source_timezone_unknown"} if direct else set()
    result.reason = (
        "evidence_requires_review" if set(result.issues) - warnings else "verified_evidence"
    )


def _entries(rows, identities) -> list[IngredientEntry]:
    return [
        IngredientEntry(name=name, sequence=seq, identity=identities.get(ingredient_id))
        for ingredient_id, name, seq in rows
        if name and (seq is None or seq > 0)
    ]


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

    def _mapping_records(self) -> list[IngredientMapping]:
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
        return records

    def _mapping(self, product_id, shade_id):
        records = self._mapping_records()
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
        if shade_id is None and shades:
            return response
        if shade_id is not None and shade_id not in {s[0] for s in shades}:
            raise ApiError(404, "Shade not found", "shade_not_found")
        mapping = self._mapping(product_id, shade_id)
        if mapping is None:
            response.reason = "mapping_not_available"
            return response
        if not _validate_mapping(response, mapping, zone, texture, shades, option_id):
            return response
        raw = await self._rows(
            _option_source().where(RawOyProductOptionRow.option_id == mapping.option_id)
        )
        if not _validate_source(response, mapping, raw[0] if raw else None):
            return response
        rows = await self._rows(
            _ingredient_rows().where(RawOyOptionIngredientRow.option_id == mapping.option_id)
        )
        _prepare_evidence(response, mapping, raw[0], rows, _source_version(raw[0], rows))
        if response.evidence is not None:
            identities = await IngredientIdentityRepository(self._session).for_entries(
                [row[0] for row in rows]
            )
            response.evidence.ingredients = _entries(rows, identities)
        return response

    async def lookup_options(
        self, selections: dict[str, str]
    ) -> dict[str, OptionIngredientInformation]:
        result = {
            option_id: OptionIngredientInformation(
                review=IngredientReadResult(
                    product_id=product_id, option_id=option_id, reason="option_label_not_available"
                )
            )
            for option_id, product_id in selections.items()
        }
        if not result:
            return result
        option_ids = list(selections)
        sources = {
            row[0]: row
            for row in await self._rows(
                _option_source().where(RawOyProductOptionRow.option_id.in_(option_ids))
            )
            if _owns_option(selections[row[0]], row)
        }
        rows_by_option = defaultdict(list)
        for row in await self._rows(
            _ingredient_rows()
            .add_columns(RawOyOptionIngredientRow.option_id)
            .where(RawOyOptionIngredientRow.option_id.in_(option_ids))
        ):
            rows_by_option[row[3]].append(row[:3])
        for option_id, raw in sources.items():
            rows = rows_by_option[option_id]
            result[option_id].observed = ObservedOptionLabel(
                source_url=raw[7],
                collected_at_raw=raw[9].isoformat() if raw[9] else None,
                source_version=_source_version(raw, rows),
                has_product_notice=bool(raw[8] and raw[8].strip()),
                parsed_row_count=len(rows),
                displayed_ingredients=[
                    DisplayedIngredient(name=name, sequence=seq)
                    for _, name, seq in rows
                    if name and name.strip()
                ],
            )
            if rows:
                result[option_id].review.reason = "mapping_not_available"

        try:
            records = self._mapping_records()
        except ApiError as exc:
            if exc.code != "ingredient_mapping_not_configured":
                for info in result.values():
                    info.error_code = exc.code
            return result

        mappings = defaultdict(list)
        for record in records:
            if record.option_id in sources and selections[record.option_id] == record.product_id:
                mappings[record.option_id].append(record)

        verified = {}
        for option_id, candidates in mappings.items():
            review = result[option_id].review
            if len(candidates) > 1:
                review.mapping_status = "ambiguous"
                review.reason = "ambiguous_option_review"
                continue
            [mapping] = candidates
            review.mapping_status = mapping.mapping_status
            review.synthetic = mapping.synthetic
            if mapping.review_status == "verified":
                verified[option_id] = mapping
            else:
                review.review_status = mapping.review_status
                review.reason = "evidence_not_reviewed"
        if not verified:
            return result

        products = list({mapping.product_id for mapping in verified.values()})
        try:
            details_rows = await self._rows(
                select(ProductRow.id, ProductRow.makeup_zone, ProductRow.texture).where(
                    ProductRow.id.in_(products)
                )
            )
            shade_rows = await self._rows(
                select(ShadeRow.id, ShadeRow.name, ShadeRow.hex, ShadeRow.product_id)
                .where(ShadeRow.product_id.in_(products))
                .order_by(ShadeRow.product_id, ShadeRow.position, ShadeRow.id)
            )
        except (SQLAlchemyError, OSError):
            for option_id in verified:
                result[option_id].error_code = "ingredient_lookup_failed"
            return result
        product_details = {row[0]: (row[1], row[2]) for row in details_rows}
        shades_by_product = defaultdict(list)
        for row in shade_rows:
            shades_by_product[row[3]].append(row[:3])

        with_evidence = {}
        for option_id, mapping in verified.items():
            info = result[option_id]
            review, raw = info.review, sources[option_id]
            details = product_details.get(mapping.product_id)
            shades = shades_by_product[mapping.product_id]
            review.shade_id = mapping.shade_id
            if (
                details is None
                or (bool(shades) and mapping.shade_id not in {s[0] for s in shades})
                or (not shades and mapping.shade_id is not None)
            ):
                review.mapping_status = "mismatch"
                review.reason = "catalog_selection_mismatch"
                continue
            if not _validate_mapping(review, mapping, *details, shades, option_id):
                continue
            if not _validate_source(review, mapping, raw):
                continue
            rows = rows_by_option[option_id]
            try:
                _prepare_evidence(review, mapping, raw, rows, info.observed.source_version)
            except ValidationError:
                info.error_code = "ingredient_evidence_invalid"
            if review.evidence is not None:
                with_evidence[option_id] = rows

        ids = sorted({row[0] for rows in with_evidence.values() for row in rows})
        try:
            identities = await IngredientIdentityRepository(self._session).for_entries(ids)
        except (SQLAlchemyError, OSError):
            identities = {}
            for option_id in with_evidence:
                result[option_id].error_code = "ingredient_identity_lookup_failed"
        for option_id, rows in with_evidence.items():
            info = result[option_id]
            try:
                info.review.evidence.ingredients = _entries(rows, identities)
            except ValidationError:
                info.review.evidence = None
                info.error_code = "ingredient_evidence_invalid"
        return result

    async def resolve_identity(self, name: str):
        return await IngredientIdentityRepository(self._session).resolve(name)
