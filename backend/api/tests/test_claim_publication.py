"""Publication checks run in a rolled-back transaction in the isolated integration database."""

import asyncio
import json
import os
import socket
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_session
from app.core.errors import ApiError
from app.main import create_app
from app.models.aihub import (
    AihubClaimPublicationRow,
    AihubClaimReviewRow,
    AihubClaimVersionRow,
    AihubDatasetReleaseRow,
    AihubKnowledgeDocumentRow,
    AihubQaCaseRawRow,
    AihubQaSourceLinkRow,
)
from app.models.raw_mfds_ingredient import RawMfdsIngredientRow
from app.repositories.claim_publication_repository import ClaimPublicationRepository
from app.schemas.catalog import Product
from app.schemas.claim_publication import (
    ClaimContext,
    ClaimIngredientKey,
    ClaimSearchRequest,
    PublishClaim,
)
from app.services.catalog_option_service import CatalogOptionService, get_catalog_option_service
from app.services.catalog_service import get_catalog_service
from app.services.claim_publication_service import (
    ClaimPublicationService,
    get_claim_publication_service,
)
from app.services.ingredient_service import IngredientService
from tests.test_catalog_options import FixtureCatalog, FixtureIngredientRepository, evidence, option

NOW = datetime(2026, 11, 10, tzinfo=UTC)
SUMMARY = "SYNTHETIC: reviewed ingredient explanation"
SOURCE = "Synthetic study citation"
NAME = "합성글리세린시험"
HASH = "a" * 64
URL = os.environ.get("TEST_DATABASE_URL")
API = "/api/catalog/ingredient-claims/search"
CHATBOT = Path(__file__).resolve().parents[2] / "chatbot"


class FixturePublicationService(ClaimPublicationService):
    async def search(self, request):
        return await self._search(request, allow_test=True)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def seed():
    if not URL:
        pytest.skip("TEST_DATABASE_URL must point to a migrated isolated PostgreSQL DB")
    engine = create_async_engine(URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection, connection.begin() as transaction:
            async with AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint"
            ) as db:
                release = AihubDatasetReleaseRow(
                    dataset_id="fixture-i3",
                    dataset_name="Synthetic release",
                    received_at=date.today(),
                    source_archive="fixture",
                    rights_status="service_approved",
                    storage_region="local",
                )
                source = AihubKnowledgeDocumentRow(
                    content_sha256=uuid4().hex,
                    source_identifier=f"fixture:{uuid4()}",
                    source_version="fixture-v1",
                    rights_status="service_approved",
                    review_status="approved",
                    title_raw="MUST_NOT_RETURN_RAW_TITLE",
                )
                ingredient = RawMfdsIngredientRow(
                    name_ko=NAME,
                    name_key=NAME,
                    source_payload={},
                    source_hash=HASH,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                    is_current=True,
                )
                db.add_all([release, source, ingredient])
                await db.flush()
                identity = ClaimIngredientKey(
                    mfds_ingredient_id=ingredient.ingredient_id, source_hash=HASH
                )
                claim = AihubClaimVersionRow(
                    claim_key=uuid4(),
                    revision=1,
                    canonical_text=SUMMARY,
                    applicability={
                        "ingredient": identity.model_dump(by_alias=True),
                        "concerns": ["건조"],
                    },
                    review_progress="completed",
                    approval_status="limited_approved",
                    approved_uses=["explain", "rank"],
                    reviewer="fixture-reviewer",
                    reviewed_at=NOW,
                    decision_reason="synthetic test only",
                )
                db.add(claim)
                await db.flush()
                review = AihubClaimReviewRow(
                    claim_version_id=claim.claim_version_id,
                    document_id=source.document_id,
                    support_status="limited",
                    rights_status="service_approved",
                    source_locator="synthetic page",
                    study_type="synthetic study type",
                    reviewer="fixture-reviewer",
                    reviewed_at=NOW.date(),
                    notes="synthetic test only",
                )
                db.add(review)
                await db.flush()
                request = PublishClaim(
                    claim_version_id=claim.claim_version_id,
                    source_review_id=review.claim_id,
                    release_id=release.release_id,
                    ingredient=identity,
                    publisher="fixture-publisher",
                    source_title=SOURCE,
                    source_url="https://example.test/study",
                )
                yield db, claim, source, review, ingredient, release, request
            await transaction.rollback()
    finally:
        await engine.dispose()


def lookup(request, *, concern="건조", use="explain"):
    return ClaimSearchRequest(
        use=use, ingredients=[request.ingredient], context=ClaimContext(concern=concern)
    )


@pytest.mark.anyio
async def test_requires_explicit_publication_and_test_rows_are_excluded_from_http(seed):
    db, *_, request = seed
    repo = ClaimPublicationRepository(db)
    service = ClaimPublicationService(repo)
    test_service = FixturePublicationService(repo)
    search = lookup(request)
    assert not (await test_service.search(search)).claims
    publication_id = await service.publish(request, test_only=True)
    assert not (await service.search(search)).claims
    claims = (await test_service.search(search)).claims
    assert len(claims) == 1 and claims[0].publication_id == publication_id
    assert claims[0].source_version == "fixture-v1"
    assert not (await test_service.search(lookup(request, concern=None))).claims
    assert not (await test_service.search(lookup(request, concern="피지"))).claims
    assert not (await test_service.search(lookup(request, use="avoid"))).claims

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        app.dependency_overrides[get_claim_publication_service] = lambda: service
        response = await client.post(API, json=search.model_dump(mode="json"))
        assert response.status_code == 200 and response.json() == {"claims": []}
        assert response.headers["cache-control"] == "no-store"
        app.dependency_overrides[get_claim_publication_service] = lambda: test_service
        body = search.model_dump(mode="json")
        body.update({"ingredients": [], "ingredientNames": [NAME]})
        response = await client.post(API, json=body)
        assert response.status_code == 200
        result = response.json()["claims"][0]
        assert result["summary"] == SUMMARY and result["sourceTitle"] == SOURCE
        assert "MUST_NOT_RETURN_RAW" not in response.text
        assert "reviewer" not in response.text and "source_locator" not in response.text
        assert (await client.post(API, json={**body, "allowTest": True})).status_code == 400


@pytest.mark.anyio
@pytest.mark.parametrize("blocked", ["claim", "review", "document", "release", "dictionary"])
async def test_publisher_rejects_unreviewed_ineligible_or_stale_inputs(seed, blocked):
    db, claim, source, review, ingredient, release, request = seed
    if blocked == "claim":
        claim.approval_status, claim.approved_uses = "on_hold", []
    elif blocked == "review":
        review.rights_status = "pending_confirmation"
    elif blocked == "document":
        source.rights_status = "pending_confirmation"
    elif blocked == "release":
        release.rights_status = "local_only"
    else:
        ingredient.source_hash = "b" * 64
    await db.flush()
    service = ClaimPublicationService(ClaimPublicationRepository(db))
    with pytest.raises(ApiError, match="publication requirements"):
        await service.publish(request, test_only=True)
    assert await db.scalar(select(func.count()).select_from(AihubClaimPublicationRow)) == 0


@pytest.mark.anyio
async def test_local_only_qa_source_cannot_be_published_via_different_release(seed):
    db, _, source, *_, request = seed
    restricted = AihubDatasetReleaseRow(
        dataset_id="restricted",
        dataset_name="Synthetic local-only dataset",
        received_at=NOW.date(),
        source_archive="fixture",
        rights_status="local_only",
        storage_region="local",
    )
    db.add(restricted)
    await db.flush()
    raw = AihubQaCaseRawRow(
        seq=str(uuid4()),
        split="train",
        source_archive="fixture",
        source_file_path="fixture",
        sha256=uuid4().hex,
        raw_json={"synthetic": "never publish"},
        release_id=restricted.release_id,
    )
    db.add(raw)
    await db.flush()
    db.add(
        AihubQaSourceLinkRow(
            seq=raw.seq,
            source_position=1,
            document_id=source.document_id,
            match_status="matched",
            quote_raw="SYNTHETIC RESTRICTED QUOTE",
        )
    )
    await db.flush()
    service = FixturePublicationService(ClaimPublicationRepository(db))
    with pytest.raises(ApiError, match="publication requirements"):
        await service.publish(request, test_only=True)
    assert not (await service.search(lookup(request))).claims


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change", ["revoke", "approval", "new_claim", "new_source", "source_review"]
)
async def test_replay_reference_stops_working_after_withdrawal_or_revision(seed, change):
    db, claim, source, review, _, _, request = seed
    service = FixturePublicationService(ClaimPublicationRepository(db))
    publication = await service.publish(request, test_only=True)
    search = ClaimSearchRequest(
        use="rank", publication_ids=[publication], context=ClaimContext(concern="건조")
    )
    assert len((await service.search(search)).claims) == 1
    if change == "revoke":
        assert await service.revoke(publication)
        assert not await service.revoke(publication)
    elif change == "approval":
        claim.approval_status, claim.approved_uses = "on_hold", []
        await db.flush()
        claim.approval_status, claim.approved_uses = "limited_approved", ["rank", "explain"]
    elif change == "new_claim":
        db.add(
            AihubClaimVersionRow(
                claim_key=claim.claim_key,
                revision=2,
                canonical_text="Not reviewed",
            )
        )
    elif change == "source_review":
        review.rights_status = "blocked"
        await db.flush()
        review.rights_status = "service_approved"
    else:
        db.add(
            AihubKnowledgeDocumentRow(
                source_identifier=source.source_identifier,
                source_version="fixture-v2",
                content_sha256=uuid4().hex,
            )
        )
    await db.flush()
    assert not (await service.search(search)).claims
    assert await db.scalar(
        select(AihubClaimPublicationRow.revoked_at).where(
            AihubClaimPublicationRow.publication_id == publication
        )
    )


@pytest.mark.anyio
async def test_concentration_and_target_are_required_when_reviewed_scope_is_limited(seed):
    db, claim, *_, request = seed
    claim.applicability = {
        **claim.applicability,
        "targets": ["성인"],
        "formulations": ["크림"],
        "concentrationMinPct": 2,
        "concentrationMaxPct": 5,
    }
    await db.flush()
    service = FixturePublicationService(ClaimPublicationRepository(db))
    await service.publish(request, test_only=True)
    search = lookup(request)
    assert not (await service.search(search)).claims
    search.context = ClaimContext(
        concern="건조", target="성인", formulation="크림", concentration_pct=3
    )
    assert len((await service.search(search)).claims) == 1
    search.context.concentration_pct = 1
    assert not (await service.search(search)).claims


@pytest.mark.anyio
async def test_chatbot_real_catalog_http_and_postgres_fixture(seed, monkeypatch):
    python = os.environ.get("VISHUE_CHATBOT_TEST_PYTHON")
    if not python:
        pytest.skip("Existing chatbot Python runtime is required")
    db, *_, publish = seed

    class ReplayFixture(FixturePublicationService):
        checks = 0

        async def search(self, request):
            if request.publication_ids:
                self.checks += 1
                if self.checks == 2:
                    await self.revoke(request.publication_ids[0])
            return await super().search(request)

    service = ReplayFixture(ClaimPublicationRepository(db))
    await service.publish(publish, test_only=True)

    catalog, ingredients = FixtureCatalog(), FixtureIngredientRepository()
    candidate = option("fixture-exact-option", 20000)
    catalog.candidates = [candidate]
    proof = evidence(candidate.option_id)
    proof.reviewed_at, proof.review_ref = NOW, "fixture-review"
    proof.ingredients[0].identity = proof.ingredients[0].identity.model_copy(
        update={"mfds_ingredient_id": publish.ingredient.mfds_ingredient_id, "name_ko": NAME}
    )
    ingredients.results[candidate.option_id] = proof

    async def reviewed(selections):
        results = await FixtureIngredientRepository.lookup_options(ingredients, selections)
        for item in results.values():
            item.review.mapping_status = "directly_reviewed"
            item.review.reviewed_at = NOW
            item.review.review_ref = "fixture-review"
            item.review.source_version = "fixture-label-version"
        return results

    ingredients.lookup_options = reviewed
    monkeypatch.setattr("app.services.ingredient_service.get_ingredient_alias_approvals", dict)

    class FixtureProducts:
        async def list_products(self, **kwargs):
            return [
                Product(
                    id=candidate.product_id,
                    name="Fixture cream",
                    name_ko="합성 크림",
                    category="skincare",
                    brand="Synthetic",
                    makeup_zone=None,
                    texture=None,
                    price_krw=1,
                    volume="",
                    shades=[],
                    description="",
                    key_ingredients=[],
                    tags=[],
                    image_url="",
                    search_keyword="",
                )
            ]

    api = create_app()
    api.dependency_overrides[get_claim_publication_service] = lambda: service
    api.dependency_overrides[get_catalog_option_service] = lambda: CatalogOptionService(
        catalog, IngredientService(ingredients)
    )
    api.dependency_overrides[get_catalog_service] = FixtureProducts
    await run_chat_probe(api, python, "fixture")


@pytest.mark.anyio
async def test_real_aihub_and_catalog_snapshots_read_only():
    rights_url = os.environ.get("VISHUE_I3_ACTUAL_AIHUB_DB_URL")
    catalog_url = os.environ.get("TEST_CATALOG_SNAPSHOT_URL")
    python = os.environ.get("VISHUE_CHATBOT_TEST_PYTHON")
    if not rights_url or not catalog_url or not python:
        pytest.skip("Requires both isolated local snapshots and the chatbot test runtime")

    def read_only_engine(url):
        return create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"server_settings": {"default_transaction_read_only": "on"}},
        )

    rights, catalog = map(read_only_engine, (rights_url, catalog_url))
    try:
        async with AsyncSession(rights) as session:
            counts = {
                "qa": await session.scalar(select(func.count()).select_from(AihubQaCaseRawRow)),
                "claimVersions": await session.scalar(
                    select(func.count()).select_from(AihubClaimVersionRow)
                ),
                "approved": await session.scalar(
                    select(func.count())
                    .select_from(AihubClaimVersionRow)
                    .where(
                        AihubClaimVersionRow.approval_status.in_(("approved", "limited_approved"))
                    )
                ),
                "publicationRows": await session.scalar(
                    select(func.count()).select_from(AihubClaimPublicationRow)
                ),
                "localOnlyReleases": await session.scalar(
                    select(func.count())
                    .select_from(AihubDatasetReleaseRow)
                    .where(AihubDatasetReleaseRow.rights_status == "local_only")
                ),
            }
            assert counts == {
                "qa": 9031,
                "claimVersions": 7,
                "approved": 0,
                "publicationRows": 0,
                "localOnlyReleases": 1,
            }
            print(json.dumps({"realAihub": counts}))

        async def catalog_session():
            async with AsyncSession(catalog) as session:
                yield session

        async def claims_service():
            async with AsyncSession(rights) as session:
                yield get_claim_publication_service(session)

        api = create_app()
        api.dependency_overrides[get_session] = catalog_session
        api.dependency_overrides[get_claim_publication_service] = claims_service
        await run_chat_probe(api, python, "actual")
    finally:
        await catalog.dispose()
        await rights.dispose()


async def run_chat_probe(api, python, mode):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api, lifespan="off", log_level="warning"))
        serving = asyncio.create_task(server.serve(sockets=[sock]))
        child = None
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started
            child = await asyncio.create_subprocess_exec(
                python,
                "-B",
                "-m",
                "tests.test_evidence_consultation",
                f"http://127.0.0.1:{port}",
                mode,
                cwd=CHATBOT,
                env=os.environ
                | {"ENV": "local", "LLM_API_KEY": "", "LLM_BASE_URL": "http://127.0.0.1:1"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, errors = await asyncio.wait_for(child.communicate(), timeout=45)
            assert child.returncode == 0, errors.decode("utf-8", errors="replace")
            print(output.decode("utf-8").strip())
        finally:
            if child and child.returncode is None:
                child.kill()
                await child.wait()
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=10)
