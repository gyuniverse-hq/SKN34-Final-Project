"""Option search fixtures and an opt-in check against the real catalog snapshot."""

import os
from datetime import UTC, datetime
from time import perf_counter
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_session
from app.main import create_app
from app.repositories.ingredient_identity_repository import IngredientIdentityRepository
from app.repositories.ingredient_repository import (
    IngredientRepository,
    catalog_fingerprint,
)
from app.schemas.catalog_options import (
    CollectedOptionPrice,
    OptionCandidate,
    OptionCategory,
    OptionIngredientInformation,
    OptionPrice,
)
from app.schemas.ingredient import (
    IngredientEntry,
    IngredientEvidence,
    IngredientIdentity,
    IngredientMapping,
    IngredientReadResult,
)
from app.services.catalog_option_service import CatalogOptionService, get_catalog_option_service
from app.services.ingredient_service import IngredientService
from tests.test_ingredient_api import observation_fingerprint, observation_fixture

PATH = "/api/catalog/options/search"
CREAM = OptionCategory(
    category_id="fixture-cream",
    parent_id="fixture-skincare",
    name="Cream",
    path="Skincare > Cream",
    depth=2,
)
PRODUCT = "oy-fixture"
CAPTURE = datetime(2026, 11, 2, tzinfo=UTC)
CAPTURE_ISO = CAPTURE.isoformat()
GLYCERIN = IngredientIdentity(
    mfds_ingredient_id=1,
    name_ko="글리세린",
    source_hash="a" * 64,
    match_method="standard_name",
    rule_version="fixture",
)
FRAGRANCE = IngredientIdentity(
    mfds_ingredient_id=2,
    name_ko="향료",
    source_hash="b" * 64,
    match_method="standard_name",
    rule_version="fixture",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FixtureCatalog:
    def __init__(self):
        self.candidates = []
        self.unavailable = False

    async def categories(self):
        return [CREAM]

    async def start_search(self, category_id):
        if self.unavailable:
            raise SQLAlchemyError("catalog unavailable")
        return CREAM if category_id == CREAM.category_id else None

    async def options(self, request):
        return len(self.candidates), self.candidates[
            request.offset : request.offset + request.limit
        ]


class FixtureIngredientRepository:
    def __init__(self):
        self.results = {}
        self.batch_calls = []
        self.identity_calls = []
        self.unavailable = False

    async def lookup_options(self, selections):
        self.batch_calls.append(selections)
        if self.unavailable:
            raise SQLAlchemyError("option source unavailable")
        return {
            option_id: OptionIngredientInformation(
                review=IngredientReadResult(
                    product_id=product_id,
                    option_id=option_id,
                    reason="evidence_not_reviewed",
                    evidence=self.results.get(option_id),
                    synthetic=True,
                )
            )
            for option_id, product_id in selections.items()
        }

    async def resolve_identity(self, name):
        self.identity_calls.append(name)
        if name == "Lookup failure":
            raise SQLAlchemyError("MFDS unavailable")
        return {"글리세린": GLYCERIN, "향료": FRAGRANCE}.get(name)


@pytest.fixture
def option_search(client, monkeypatch):
    monkeypatch.setattr("app.services.ingredient_service.get_ingredient_alias_approvals", dict)
    catalog = FixtureCatalog()
    ingredients = FixtureIngredientRepository()
    service = CatalogOptionService(catalog, IngredientService(ingredients))
    client.app.dependency_overrides[get_catalog_option_service] = lambda: service

    def search(**request):
        return client.post(PATH, json={"categoryId": CREAM.category_id, **request})

    return catalog, ingredients, search


def option(option_id, sale, *, stamp=CAPTURE_ISO, has_snapshot=True):
    return OptionCandidate(
        product_id=PRODUCT,
        product_name="Fixture cream",
        catalog_category="skincare",
        category=CREAM,
        option_id=option_id,
        option_name=option_id,
        price=OptionPrice(
            reference_price_krw=9900,
            collected=CollectedOptionPrice(
                evidence_id=f"fixture-price:{option_id}",
                source_url="https://example.test",
                sale_price_krw=sale,
                list_price_krw=40000,
                collected_at_raw=stamp,
                stock_status="in_stock",
            )
            if has_snapshot
            else None,
        ),
    )


def evidence(option_id, *, coverage="full", contains_fragrance=False):
    entries = [IngredientEntry(name="글리세린", sequence=1, identity=GLYCERIN)]
    if contains_fragrance:
        entries.append(IngredientEntry(name="향료", sequence=2, identity=FRAGRANCE))
    return IngredientEvidence(
        product_id=PRODUCT,
        option_id=option_id,
        evidence_id=f"fixture-evidence:{option_id}",
        source="option_ingredients",
        source_ref="https://example.test",
        collected_at=CAPTURE,
        mapping_status="verified",
        review_status="verified",
        ingredient_coverage=coverage,
        normalization_status="verified",
        ingredients=entries,
        synthetic=True,
    )


def condition(name, operator="includes"):
    return {"ingredientName": name, "operator": operator}


def test_budget_uses_only_the_selected_capture_and_only_when_requested(option_search):
    catalog, _, search = option_search
    catalog.candidates = [
        option("boundary", 20000),
        option("over", 20001),
        option("no-capture", None, has_snapshot=False),
        option("no-time", 15000, stamp=None),
    ]
    observed = search(priceBasis="collected_sale", maxPriceKRW=20000).json()
    assert [row["optionId"] for row in observed["matches"]] == ["boundary"]
    assert observed["excluded"][0]["budgetCondition"] == {
        "condition": "budget",
        "priceBasis": "collected_sale",
        "maxPriceKRW": 20000,
        "verdict": "NOT_MATCH",
        "reason": "over_budget_at_collection",
        "evidenceId": "fixture-price:over",
    }
    assert [row["optionId"] for row in observed["unconfirmed"]] == ["no-capture", "no-time"]
    current = search(maxPriceKRW=20000).json()
    assert current["status"] == "unconfirmed"
    assert len(current["unconfirmed"]) == 4
    for row in current["unconfirmed"]:
        assert row["price"]["currentSalePriceKRW"] is None
        assert row["price"]["currentStockStatus"] == "unknown"
        assert row["budgetCondition"]["reason"] == "current_sale_price_unverified"


def test_compound_conditions_keep_known_violation_with_unknown_and_error(option_search):
    catalog, repo, search = option_search
    catalog.candidates = [option("excluded", 18000), option("partial", 18000)]
    repo.results = {
        "excluded": evidence("excluded", contains_fragrance=True),
        "partial": evidence("partial", coverage="partial"),
    }
    filters = [
        condition("글리세린"),
        condition("향료", "excludes"),
        condition("Unresolved"),
        condition("Lookup failure"),
    ]
    result = search(ingredientConditions=filters).json()
    assert result["status"] == "partial_failure"
    assert result["scope"]["request"]["ingredientConditions"] == filters
    excluded = result["excluded"][0]
    assert excluded["requiredVerdict"] == "NOT_MATCH"
    checks = excluded["ingredients"]["review"]["conditions"]
    assert [item["verdict"] for item in checks] == ["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    assert all(item["evidenceId"] == "fixture-evidence:excluded" for item in checks)
    assert checks[1]["reason"] == "ingredient_present"
    assert checks[3]["reason"] == "ingredient_identity_lookup_failed"
    assert result["unconfirmed"][0]["requiredVerdict"] == "ERROR"
    assert repo.batch_calls == [{"excluded": PRODUCT, "partial": PRODUCT}]
    assert repo.identity_calls == [item["ingredientName"] for item in filters]


def test_verified_exact_absence_partial_unknown_and_stale_review(option_search):
    catalog, repo, search = option_search
    catalog.candidates = [
        option("full", 20000),
        option("partial", 20000),
        option("unreviewed", 20000),
    ]
    repo.results = {"full": evidence("full"), "partial": evidence("partial", coverage="partial")}
    filters = [condition("글리세린"), condition("향료", "excludes")]
    data = search(ingredientConditions=filters).json()
    full = data["matches"][0]
    assert full["optionId"] == "full"
    assert full["ingredients"]["review"]["conditions"][1]["reason"] == "ingredient_absent"
    by_id = {row["optionId"]: row for row in data["unconfirmed"]}
    assert (
        by_id["partial"]["ingredients"]["review"]["conditions"][1]["reason"]
        == "absence_not_verifiable"
    )
    assert by_id["unreviewed"]["ingredients"]["review"]["conditions"][0]["verdict"] == "UNKNOWN"
    stale = search(
        ingredientConditions=filters,
        ingredientEvidenceSince="2026-11-03T00:00:00Z",
    ).json()
    assert stale["matches"] == []
    stale_full = stale["unconfirmed"][0]["ingredients"]["review"]["conditions"]
    assert {item["reason"] for item in stale_full} == {"ingredient_evidence_stale"}
    assert all(item["evidenceId"] == "fixture-evidence:full" for item in stale_full)


def test_whole_source_error_keeps_known_budget_violation(option_search):
    catalog, repo, search = option_search
    catalog.candidates = [option("over", 25000), option("within", 15000)]
    repo.unavailable = True
    data = search(
        priceBasis="collected_sale",
        maxPriceKRW=20000,
        ingredientConditions=[condition("향료", "excludes")],
    ).json()
    assert data["status"] == "partial_failure"
    assert data["scope"]["optionsWithLookupErrors"] == 2
    assert data["excluded"][0]["requiredVerdict"] == "NOT_MATCH"
    assert data["unconfirmed"][0]["requiredVerdict"] == "ERROR"
    assert (
        data["excluded"][0]["ingredients"]["review"]["conditions"][0]["reason"]
        == "ingredient_lookup_failed"
    )


def test_scope_distinguishes_no_matches_incomplete_unsupported_and_failure(option_search):
    catalog, _, search = option_search
    catalog.candidates = [option("one", 5000), option("two", 6000)]
    query = {"priceBasis": "collected_sale", "maxPriceKRW": 1000}
    complete = search(**query).json()
    assert complete["status"] == "no_matches" and complete["scope"]["exhaustive"]
    incomplete = search(**query, limit=1).json()
    assert incomplete["status"] == "search_incomplete"
    assert incomplete["scope"]["nextOffset"] == 1
    last = search(**query, limit=1, offset=1).json()
    assert last["status"] == "search_incomplete"
    assert last["scope"]["nextOffset"] is None and not last["scope"]["exhaustive"]
    unsupported = search(categoryId="fictional")
    assert unsupported.status_code == 400 and unsupported.json()["code"] == "unsupported_category"
    assert search(optionId="one").json()["code"] == "invalid_request"
    assert search(limit=33).json()["code"] == "invalid_request"
    catalog.unavailable = True
    failed = search()
    assert failed.status_code == 503 and failed.json()["code"] == "catalog_option_lookup_failed"


@pytest.mark.anyio
async def test_repository_batches_verified_options_and_checks_versions_and_ownership(monkeypatch):
    def source(option_id, goods_no="FIXTURE"):
        return (
            option_id,
            goods_no,
            None,
            option_id,
            None,
            CAPTURE,
            None,
            "https://example.test",
            "글리세린" if option_id == "first" else "향료",
            CAPTURE,
            None,
        )

    first, second, foreign = source("first"), source("second"), source("foreign", "OTHER")
    first_rows = [(1, "글리세린", 1)]
    second_rows = [(2, "향료", 1)]
    mappings = [
        IngredientMapping(
            product_id=PRODUCT,
            option_id=raw[0],
            goods_no="FIXTURE",
            mapping_status="directly_reviewed",
            mapping_method="direct_review",
            reviewed_by="fixture",
            reviewed_at=CAPTURE,
            review_ref="fixture",
            catalog_fingerprint=catalog_fingerprint(PRODUCT, None, None, []),
            source_version=observation_fingerprint(raw, rows),
            review_status="verified",
            ingredient_coverage="full",
            normalization_status="verified",
            synthetic=True,
        )
        for raw, rows in ((first, first_rows), (second, second_rows))
    ]
    mappings[1].source_version = "stale-hash"
    repository = IngredientRepository(None, mappings=mappings)
    repository._rows = AsyncMock(
        side_effect=[
            [first, second, foreign],
            [
                (observation_fixture(first, first_rows),),
                (observation_fixture(second, second_rows),),
            ],
            [(PRODUCT, None, None)],
            [],
        ]
    )
    load_identities = AsyncMock(return_value={1: GLYCERIN})
    monkeypatch.setattr(IngredientIdentityRepository, "for_entries", load_identities)
    options = await repository.lookup_options(
        dict.fromkeys(("first", "second", "foreign"), PRODUCT)
    )
    assert repository._rows.await_count == 4
    load_identities.assert_awaited_once_with([1])
    assert options["first"].review.evidence.ingredients[0].identity == GLYCERIN
    assert options["second"].review.reason == "source_version_mismatch"
    assert options["second"].review.evidence is None
    assert options["second"].observed.displayed_ingredients[0].name == "향료"
    assert options["foreign"].observed is None
    assert options["foreign"].review.evidence is None


REAL_URL = os.environ.get("TEST_CATALOG_SNAPSHOT_URL")


@pytest.mark.anyio
async def test_product_and_option_paths_read_the_same_versioned_original(monkeypatch):
    raw = (
        "fixture-001",
        "FIXTURE",
        None,
        "single",
        None,
        CAPTURE,
        None,
        "https://example.test",
        "글리세린,글리세린",
        CAPTURE,
        None,
    )
    rows = [(1, "글리세린", 1), (1, "글리세린", 2)]
    observation = observation_fixture(raw, rows)
    mapping = IngredientMapping(
        product_id=PRODUCT,
        option_id=raw[0],
        goods_no="FIXTURE",
        mapping_status="directly_reviewed",
        mapping_method="direct_review",
        reviewed_by="synthetic",
        reviewed_at=CAPTURE,
        review_ref="fixture://review",
        catalog_fingerprint=catalog_fingerprint(PRODUCT, None, None, []),
        source_version=observation_fingerprint(raw, rows),
        review_status="verified",
        ingredient_coverage="full",
        normalization_status="verified",
        synthetic=True,
    )
    monkeypatch.setattr(
        IngredientIdentityRepository, "for_entries", AsyncMock(return_value={1: GLYCERIN})
    )
    direct = IngredientRepository(None, mappings=[mapping])
    direct._rows = AsyncMock(side_effect=[[(PRODUCT, None, None)], [], [raw], [(observation,)]])
    batch = IngredientRepository(None, mappings=[mapping])
    batch._rows = AsyncMock(side_effect=[[raw], [(observation,)], [(PRODUCT, None, None)], []])
    single = await direct.lookup(PRODUCT, None, raw[0])
    option = (await batch.lookup_options({raw[0]: PRODUCT}))[raw[0]]
    assert single.source_version == option.review.source_version
    assert single.evidence == option.review.evidence
    assert [e.sequence for e in single.evidence.ingredients] == [1, 2]
    assert [e.name for e in option.observed.displayed_ingredients] == ["글리세린", "글리세린"]


REAL_CREAM = "1000001000100150001"


@pytest.mark.integration
@pytest.mark.skipif(not REAL_URL, reason="needs read-only TEST_CATALOG_SNAPSHOT_URL")
def test_real_snapshot_cream_options_and_bounded_query_count(monkeypatch, tmp_path):
    engine = create_async_engine(
        REAL_URL,
        poolclass=NullPool,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    queries = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_queries(_conn, _cursor, statement, *_):
        queries.append(statement)

    async def read_session():
        async with AsyncSession(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = read_session
    client = TestClient(app)

    def search(**request):
        response = client.post(PATH, json={"categoryId": REAL_CREAM, **request})
        assert response.status_code == 200, response.text
        return response.json()

    categories = client.get("/api/catalog/categories")
    assert categories.status_code == 200
    cream = next(row for row in categories.json()["categories"] if row["categoryId"] == REAL_CREAM)
    assert cream["parentId"] == "100000100010015"
    assert cream["path"] == "뷰티 > 스킨케어 > 크림 > 크림"

    query_counts = []
    under_budget = {"priceBasis": "collected_sale", "maxPriceKRW": 20000}
    for limit in (4, 32):
        queries.clear()
        start = perf_counter()
        page = search(limit=limit, **under_budget)
        query_counts.append(len(queries))
        print(
            f"Real cream snapshot limit={limit}: {len(queries)} SQL statements, "
            f"{(perf_counter() - start) * 1000:.0f} ms"
        )
        assert page["scope"]["candidateCount"] == 808
        assert page["scope"]["nextOffset"] == limit
        assert len(page["matches"]) == limit
        assert all(row["category"]["categoryId"] == REAL_CREAM for row in page["matches"])
        assert all(row["price"]["collected"]["salePriceKRW"] <= 20000 for row in page["matches"])
    assert query_counts[0] == query_counts[1] <= 7
    stamps = {row["price"]["collected"]["collectedAtRaw"] for row in page["matches"]}
    assert len(stamps) > 1
    boundary = search(limit=32, offset=160, **under_budget)
    assert len(boundary["matches"]) == 23 and len(boundary["excluded"]) == 9
    parent = search(categoryId=cream["parentId"], limit=1)
    assert parent["scope"]["candidateCount"] > 808

    product_id = "oy-a000000257838"
    data = search(productId=product_id, maxPriceKRW=50000, priceBasis="collected_sale")
    assert data["scope"]["exhaustive"]
    rows = {row["optionId"]: row for row in data["matches"] + data["excluded"]}
    for suffix, sale in (("001", 84600), ("002", 40610), ("003", 54990)):
        row = rows[f"A000000257838-{suffix}"]
        assert row["productId"] == product_id
        assert row["price"]["collected"]["salePriceKRW"] == sale
        assert row["price"]["currentSalePriceKRW"] is None
        assert row["price"]["currentStockStatus"] == "unknown"
        assert row["ingredients"]["observed"]["parsedRowCount"] == 0
        assert row["ingredients"]["observed"]["observationVersion"] is None
        assert row["ingredients"]["observed"]["displayedIngredients"] == []
        assert row["ingredients"]["review"]["reviewStatus"] == "unreviewed"
    options = list(rows.values())
    assert (
        options[0]["ingredients"]["observed"]["sourceVersion"]
        != options[1]["ingredients"]["observed"]["sourceVersion"]
    )

    checked = search(
        productId=product_id,
        maxPriceKRW=50000,
        priceBasis="collected_sale",
        ingredientConditions=[condition("글리세린"), condition("향료", "excludes")],
    )
    assert checked["matches"] == []
    assert checked["unconfirmed"][0]["optionId"] == "A000000257838-002"
    assert all(
        item["verdict"] == "UNKNOWN"
        for item in checked["unconfirmed"][0]["ingredients"]["review"]["conditions"]
    )
    assert {row["optionId"] for row in checked["excluded"]} >= {
        "A000000257838-001",
        "A000000257838-003",
    }
    assert (
        search(productId=product_id, priceBasis="collected_sale", maxPriceKRW=1000)["status"]
        == "no_matches"
    )
    assert search(productId=product_id, maxPriceKRW=50000)["status"] == "unconfirmed"
    foreign = search(limit=1, **under_budget)["matches"][0]
    assert foreign["productId"] != product_id
    assert (
        search(productId=product_id, optionId=foreign["optionId"])["scope"]["candidateCount"] == 0
    )

    # Fault injection on the actual catalog. The snapshot stays read-only.
    monkeypatch.setenv("INGREDIENT_MAPPING_PATH", str(tmp_path / "unavailable-review.json"))
    failed = search(
        productId=product_id,
        maxPriceKRW=50000,
        priceBasis="collected_sale",
        ingredientConditions=[condition("글리세린")],
    )
    assert failed["status"] == "partial_failure"
    assert failed["scope"]["optionsWithLookupErrors"] == 4
    assert {row["optionId"] for row in failed["excluded"]} >= {
        "A000000257838-001",
        "A000000257838-003",
    }
    assert failed["unconfirmed"][0]["optionId"] == "A000000257838-002"
    assert failed["unconfirmed"][0]["ingredients"]["errorCode"] == "ingredient_mapping_missing"
    assert failed["unconfirmed"][0]["requiredVerdict"] == "ERROR"
