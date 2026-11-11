"""Populate only a run-bound, empty I-3 test PostgreSQL database.

This module must run with #229 backend/api as its working directory and Python
environment. No production data or actual AIHub QA is read. No tables are
cleared. The caller must additionally verify the Docker container labels/ports.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from app.repositories.claim_publication_repository import ClaimPublicationRepository
from app.schemas.claim_publication import ClaimIngredientKey, PublishClaim
from app.services.claim_publication_service import ClaimPublicationService
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.errors import ApiError
from app.models.aihub import (
    AihubClaimReviewRow,
    AihubClaimVersionRow,
    AihubDatasetReleaseRow,
    AihubKnowledgeDocumentRow,
)
from app.models.catalog import ProductRow
from app.models.oy_mfds_ingredient_map import OyMfdsIngredientMapRow
from app.models.raw_mfds_ingredient import RawMfdsIngredientRow
from app.models.raw_oliveyoung import (
    RawOyCategoryRow,
    RawOyIngredientRow,
    RawOyOptionIngredientRow,
    RawOyPriceSnapshotRow,
    RawOyProductNoticeRow,
    RawOyProductOptionRow,
    RawOyProductRow,
)
from app.repositories.ingredient_repository import (
    _ingredient_rows,
    _option_source,
    _source_version,
    catalog_fingerprint,
)
from app.schemas.ingredient import IngredientMapping

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "docs/ai-alignment/04_i3_eval/fixtures.synthetic.json"
ALLOWED_MAPPING = Path(
    "C:/Users/playdata2/.codex/visualizations/2026/11/11/"
    "01a1c95a-645e-7e00-a435-7ab332cfafb4/i3-ingredient-mapping.json"
)
STAMP = datetime(2026, 11, 10, 9, 0)
REVIEWED = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
IDS = {"SYN-G": 70001, "SYN-F": 70002, "SYN-A": 70003}
NAMES = {"SYN-G": "글리세린", "SYN-F": "향료", "SYN-A": "성분 A"}
SOURCE_HASH = hashlib.sha256(b"synthetic-dictionary-v1").hexdigest()
CATEGORY = "i3-fixture-cream"
PUBLICATION_ID = UUID("00000000-0000-4000-8000-000000000001")
RUN_ID = re.compile(r"^[a-f0-9]{32}$")
SCENARIO = re.compile(r"^(Q0[1-6]|E0[1-6]|I0[1-6]|O(0[1-9]|10)|M0[1-8])$")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_target(database_url, isolation_token, mapping_path):
    """Validate client-side constraints; never accept remote, arbitrary DB or path."""
    if not RUN_ID.fullmatch(isolation_token or ""):
        raise ValueError("Run ID must be 32 lowercase hexadecimal characters")
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.port is None
        or url.database != "i3_eval"
        or url.username != "i3_eval"
        or url.query
    ):
        raise ValueError("Only explicit loopback i3_eval PostgreSQL is allowed")
    if (
        not Path(mapping_path).is_absolute()
        or Path(mapping_path).resolve() != ALLOWED_MAPPING.resolve()
    ):
        raise ValueError("Mapping output path must be the approved absolute path")
    return url


def load_scenario(fixture_path, scenario):
    if not SCENARIO.fullmatch(scenario):
        raise ValueError("Unknown scenario")
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if fixture.get("synthetic") is not True or fixture.get("productionEvidence") is not False:
        raise ValueError("Fixture must explicitly be synthetic and non-production")
    spec = fixture["scenarios"][scenario]
    by_id = {row["optionId"]: dict(row) for row in fixture["baseOptions"]}
    options = [by_id[option_id].copy() for option_id in spec["baseOptions"]]
    overrides = spec["overrides"]
    for option in options:
        prefix = option["optionId"] + "."
        for key, value in overrides.items():
            if key.startswith(prefix):
                option[key[len(prefix) :]] = value
    for row in overrides.get("comparison", []):
        option = {
            "productId": row["productId"],
            "optionId": row["optionId"],
            "collectedSalePriceKRW": None,
            "collectedAtRaw": None,
            "currentStockStatus": "unknown",
            "coverage": "full",
            "verification": "verified",
            "ingredientIds": row["ingredientIds"],
        }
        options.append(option)
    generated = overrides.get("generateOptions")
    if generated:
        options = [
            {
                "productId": generated["productId"],
                "optionId": f"{generated['optionPrefix']}{i:03d}",
                "collectedSalePriceKRW": generated["collectedSalePriceKRW"],
                "collectedAtRaw": "2026-11-10 09:00",
                "currentStockStatus": "unknown",
                "coverage": "full",
                "verification": "verified",
                "ingredientIds": ["SYN-G"],
            }
            for i in range(generated["count"])
        ]
    if len({o["optionId"] for o in options}) != len(options):
        raise ValueError("Duplicate option ID")
    if any(o["productId"] not in {"syn-a", "syn-b"} for o in options):
        raise ValueError("Unmapped synthetic product")
    if any(i not in IDS for o in options for i in o["ingredientIds"]):
        raise ValueError("Unmapped synthetic ingredient")
    fixture_hash = digest(
        {"shared": {k: v for k, v in fixture.items() if k != "scenarios"}, "scenario": spec}
    )
    return fixture, spec, options, fixture_hash


async def verify_server(connection, run_id):
    row = (
        await connection.execute(
            text("SELECT current_database(), current_user, current_setting('i3_eval.run_id', true)")
        )
    ).one()
    if tuple(row) != ("i3_eval", "i3_eval", run_id):
        raise ValueError("Database identity/run marker does not match isolated run")


async def assert_empty(session):
    # Never delete, truncate, replace or reuse an occupied DB.
    for model in (ProductRow, RawOyCategoryRow, RawMfdsIngredientRow, AihubDatasetReleaseRow):
        if await session.scalar(select(func.count()).select_from(model)):
            raise ValueError("Database is not an empty migrated test database")


async def seed_database(
    database_url, isolation_token, mapping_path, scenario, fixture_path=FIXTURE
):
    url = validate_target(database_url, isolation_token, mapping_path)
    fixture, spec, options, fixture_hash = load_scenario(fixture_path, scenario)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await verify_server(connection, isolation_token)
            await connection.commit()
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                await assert_empty(db)
                db.add(
                    RawOyCategoryRow(
                        category_no=CATEGORY,
                        category_name="크림",
                        category_path="스킨케어 > 크림",
                        depth=1,
                    )
                )
                for logical, identifier in IDS.items():
                    db.add(
                        RawMfdsIngredientRow(
                            ingredient_id=identifier,
                            name_ko=NAMES[logical],
                            name_key=NAMES[logical],
                            source_payload={"synthetic": "true"},
                            source_hash=SOURCE_HASH,
                            first_seen_at=REVIEWED,
                            last_seen_at=REVIEWED,
                            is_current=True,
                        )
                    )
                    db.add(
                        RawOyIngredientRow(
                            ingredient_id=identifier,
                            ingredient_name=NAMES[logical],
                            ingredient_norm=NAMES[logical].upper(),
                        )
                    )
                await db.flush()
                for identifier in IDS.values():
                    db.add(
                        OyMfdsIngredientMapRow(
                            oy_ingredient_id=identifier,
                            mfds_ingredient_id=identifier,
                            match_method="exact_name",
                            rule_version="synthetic-v1",
                        )
                    )
                products = sorted({o["productId"] for o in options})
                for position, logical in enumerate(products):
                    physical = "oy-" + logical
                    db.add(
                        ProductRow(
                            id=physical,
                            position=position,
                            brand="Synthetic",
                            name=f"Synthetic {logical}",
                            name_ko=f"합성 크림 {logical}",
                            category="skincare",
                            makeup_zone=None,
                            texture=None,
                            price_krw=9999,
                            volume="",
                            description="",
                            key_ingredients=[],
                            tags=[],
                            image_url="",
                            search_keyword="",
                            search_text=f"합성 크림 {logical}",
                        )
                    )
                    db.add(
                        RawOyProductRow(
                            goods_no=logical,
                            category_no=CATEGORY,
                            goods_name=f"합성 크림 {logical}",
                            product_url=f"https://example.invalid/{logical}",
                            is_in_catalog=True,
                        )
                    )
                await db.flush()
                for logical in products:
                    names = sorted(
                        {
                            NAMES[k]
                            for o in options
                            if o["productId"] == logical
                            for k in o["ingredientIds"]
                        }
                    )
                    db.add(
                        RawOyProductNoticeRow(
                            goods_no=logical,
                            ingredients_raw=", ".join(names) or "합성 전성분 없음",
                            collected_at=STAMP,
                        )
                    )
                price_rows = []
                for index, option in enumerate(options):
                    db.add(
                        RawOyProductOptionRow(
                            option_id=option["optionId"],
                            goods_no=option["productId"],
                            option_name=option["optionId"],
                            collected_at=STAMP,
                        )
                    )
                    price_rows.append(
                        RawOyPriceSnapshotRow(
                            snapshot_id=80000 + index,
                            option_id=option["optionId"],
                            sale_price=option.get("collectedSalePriceKRW"),
                            list_price=40000,
                            is_sold_out=False,
                            is_latest=True,
                            collected_at=(
                                datetime.fromisoformat(option["collectedAtRaw"])
                                if option.get("collectedAtRaw")
                                else None
                            ),
                        )
                    )
                await db.flush()
                db.add_all(price_rows)
                await db.flush()
                for option in options:
                    for sequence, ingredient in enumerate(option["ingredientIds"], 1):
                        db.add(
                            RawOyOptionIngredientRow(
                                option_id=option["optionId"],
                                ingredient_id=IDS[ingredient],
                                seq=sequence,
                            )
                        )
                await db.flush()
                mappings = []
                logical_versions = {}
                for option in options:
                    oid = option["optionId"]
                    raw = (
                        await db.execute(
                            _option_source().where(RawOyProductOptionRow.option_id == oid)
                        )
                    ).one()
                    rows = (
                        await db.execute(
                            _ingredient_rows().where(RawOyOptionIngredientRow.option_id == oid)
                        )
                    ).all()
                    version = _source_version(raw, rows)
                    physical = "oy-" + option["productId"]
                    verified = option.get("verification") == "verified"
                    mapping = IngredientMapping(
                        product_id=physical,
                        option_id=oid,
                        shade_id=None,
                        goods_no=option["productId"],
                        mapping_status="directly_reviewed",
                        mapping_method="direct_review",
                        reviewed_by="synthetic-reviewer",
                        reviewed_at=REVIEWED,
                        review_ref="synthetic-fixture-only",
                        catalog_fingerprint=catalog_fingerprint(physical, None, None, []),
                        source_version=version,
                        review_status="verified" if verified else "unreviewed",
                        ingredient_coverage=option.get("coverage", "unknown"),
                        normalization_status="verified" if verified else "unverified",
                        synthetic=True,
                    )
                    mappings.append(mapping.model_dump(mode="json", by_alias=True))
                    logical_versions[oid] = version
                publication = None
                blocked = None
                if spec["publication"] == "basePublication" or scenario == "E03":
                    overrides = spec["overrides"]
                    logical = overrides.get("publication.ingredientId", "SYN-G")
                    identity = ClaimIngredientKey(
                        mfds_ingredient_id=IDS[logical], source_hash=SOURCE_HASH
                    )
                    restricted = scenario == "E03"
                    release = AihubDatasetReleaseRow(
                        dataset_id="synthetic-i3-fixture",
                        dataset_name="Synthetic only",
                        received_at=date(2026, 11, 10),
                        source_archive="synthetic",
                        rights_status="local_only" if restricted else "service_approved",
                        storage_region="local",
                    )
                    source = AihubKnowledgeDocumentRow(
                        content_sha256=hashlib.sha256(b"synthetic-doc").hexdigest(),
                        source_identifier="synthetic-i3-study",
                        source_version="fixture-v1",
                        rights_status="service_approved",
                        review_status="approved",
                        title_raw="Synthetic fixture",
                    )
                    db.add_all([release, source])
                    await db.flush()
                    applicability = {"ingredient": identity.model_dump(by_alias=True)}
                    limited = overrides.get("publication.applicability")
                    if limited:
                        applicability.update(
                            {
                                "targets": [limited["target"]],
                                "formulations": [limited["formulation"]],
                                "concentrationMinPct": limited["concentrationMinPct"],
                                "concentrationMaxPct": limited["concentrationMaxPct"],
                            }
                        )
                    claim = AihubClaimVersionRow(
                        claim_key=UUID("00000000-0000-4000-8000-000000000002"),
                        revision=1,
                        canonical_text=fixture["basePublication"]["summary"],
                        applicability=applicability,
                        review_progress="completed",
                        approval_status="limited_approved" if limited else "approved",
                        approved_uses=overrides.get("publication.uses", ["explain", "rank"]),
                        reviewer="synthetic-reviewer",
                        reviewed_at=REVIEWED,
                        decision_reason="synthetic isolated fixture only",
                    )
                    db.add(claim)
                    await db.flush()
                    review = AihubClaimReviewRow(
                        claim_version_id=claim.claim_version_id,
                        document_id=source.document_id,
                        support_status="limited",
                        rights_status="service_approved",
                        source_locator="synthetic",
                        study_type="synthetic",
                        reviewer="synthetic-reviewer",
                        reviewed_at=REVIEWED.date(),
                        notes="synthetic isolated fixture only",
                    )
                    db.add(review)
                    await db.flush()
                    request = PublishClaim(
                        claim_version_id=claim.claim_version_id,
                        source_review_id=review.claim_id,
                        release_id=release.release_id,
                        ingredient=identity,
                        publisher="synthetic-publisher",
                        source_title="Synthetic test citation",
                        source_url="https://example.invalid/i3-synthetic",
                    )
                    service = ClaimPublicationService(ClaimPublicationRepository(db))
                    try:
                        with patch(
                            "app.services.claim_publication_service.uuid4",
                            return_value=PUBLICATION_ID,
                        ):
                            publication = str(await service.publish(request, test_only=True))
                    except ApiError as exc:
                        if not restricted or exc.status != 409:
                            raise
                        blocked = {"status": exc.status, "code": exc.code}
                    if restricted and blocked is None:
                        raise ValueError("Synthetic local_only publication unexpectedly succeeded")
                artifact = {"schemaVersion": 1, "records": mappings}
                # Write only the exact approved artifact, after server/run/empty checks.
                await asyncio.to_thread(
                    Path(mapping_path).write_text,
                    json.dumps(artifact, ensure_ascii=False),
                    encoding="utf-8",
                )
                await db.commit()
                snapshot = {
                    "scenario": scenario,
                    "options": options,
                    "mapping": mappings,
                    "publicationId": publication,
                    "blockedPublication": blocked,
                }
                return {
                    "synthetic": True,
                    "scenario": scenario,
                    "fixtureHash": fixture_hash,
                    "dictionaryHash": SOURCE_HASH,
                    "dataSnapshotHash": digest(snapshot),
                    "logicalToPhysicalProduct": {x: "oy-" + x for x in products},
                    "logicalToPhysicalOption": {o["optionId"]: o["optionId"] for o in options},
                    "logicalToPhysicalIngredient": IDS,
                    "optionSourceVersions": logical_versions,
                    "publicationId": publication,
                    "publicationTestOnly": publication is not None,
                    "publicationIdInjectedAtCreation": publication is not None,
                    "localOnlyPublishAttempt": blocked,
                    "limitations": [
                        "current_sale and currentStockStatus remain unknown in real Catalog",
                        "I05 approved alias requires an independent alias policy fixture",
                        "test-only publications require explicit isolated-only service override",
                    ],
                }
    finally:
        await engine.dispose()


async def revoke_publication(database_url, isolation_token, mapping_path, publication_id):
    url = validate_target(database_url, isolation_token, mapping_path)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await verify_server(connection, isolation_token)
            await connection.commit()
            async with AsyncSession(bind=connection) as db:
                service = ClaimPublicationService(ClaimPublicationRepository(db))
                changed = await service.revoke(UUID(publication_id))
                await db.commit()
                return {"synthetic": True, "revoked": changed, "publicationId": publication_id}
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--isolation-token", required=True)
    parser.add_argument("--mapping-path", required=True)
    parser.add_argument("--fixture-path", default=str(FIXTURE))
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--revoke-publication")
    args = parser.parse_args()
    if args.revoke_publication:
        result = asyncio.run(
            revoke_publication(
                args.database_url, args.isolation_token, args.mapping_path, args.revoke_publication
            )
        )
    else:
        result = asyncio.run(
            seed_database(
                args.database_url,
                args.isolation_token,
                args.mapping_path,
                args.scenario,
                args.fixture_path,
            )
        )
    # Manifest contains no database URL, password, user secret or raw QA.
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
