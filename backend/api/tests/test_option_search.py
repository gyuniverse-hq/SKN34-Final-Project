"""G4 synthetic repository/HTTP tests; no live Catalog, Redis or LLM."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_option_search_rate_limiter
from app.main import create_app
from app.repositories.ingredient_identity_repository import OptionIngredientMatch
from app.repositories.ingredient_repository import fingerprint
from app.schemas.ingredient import (
    IngredientEvidence,
    IngredientIdentity,
    IngredientMapping,
    IngredientReadResult,
    ReviewedOptionEvidence,
)
from app.schemas.option_search import OptionSearchRequest
from app.services.option_search_service import OptionSearchService, get_option_search_service
from tests.conftest import make_product


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Repositories:
    def __init__(self):
        self.products = [
            make_product(
                "fixture-product", "lip", [("s1", "01", "#112233"), ("s2", "02", "#334455")]
            )
        ]
        self.unmapped = set()
        self.fail = False
        self.slow = False
        self.name_calls = []
        self.name_matches = {}
        self.entry_identity = None
        self.product_types = {}
        self.priority = set()
        self.reviewed_texture_keys = set()
        self.lookup_calls = []
        self.stamp = datetime(2026, 11, 1, tzinfo=UTC)

    async def option_search_candidates(self, query, category, ids, limit, *, product_type=None):
        rows = [
            p
            for p in self.products
            if (ids is None or p.id in ids)
            and (not category or p.category == category)
            and (not query or query in p.id)
        ]
        if product_type:
            rows = [p for p in rows if self.product_types.get(p.id) == (product_type, product_type)]
        return rows[:limit], len(rows)

    def prioritized_option_keys(self, keys=None, *, reviewed_texture=None):
        if reviewed_texture == "matte":
            return self.reviewed_texture_keys
        return self.priority & keys

    async def lookup(self, pid, sid):
        self.lookup_calls.append((pid, sid))
        if self.fail:
            raise SQLAlchemyError("synthetic failure")
        if sid in self.unmapped:
            return IngredientReadResult(product_id=pid, shade_id=sid, reason="unmapped")
        oid = f"option-{sid}"
        evidence = IngredientEvidence(
            product_id=pid,
            shade_id=sid,
            option_id=oid,
            evidence_id=f"SYNTHETIC:{oid}",
            ingredients=[{"name": "Panthenol", "sequence": 1, "identity": self.entry_identity}],
            ingredient_coverage="partial",
            source="option_ingredients",
            source_ref="fixture://only",
            collected_at=self.stamp,
            review_status="verified",
            mapping_status="verified",
            normalization_status="unverified",
            synthetic=True,
        )
        return IngredientReadResult(
            product_id=pid,
            shade_id=sid,
            option_id=oid,
            mapping_status="directly_reviewed",
            source_version="synthetic-v1",
            reason="fixture",
            synthetic=True,
            evidence=evidence,
        )

    async def resolve_option_name(self, name):
        self.name_calls.append(name)
        return self.name_matches.get(name, OptionIngredientMatch())

    async def product_texture(self, product_id):
        return ("matte", "product_name", self.stamp, "fixture://product")

    async def option_price(self, oid, product_id):
        if self.slow:
            await asyncio.sleep(1)
        return ("snapshot-1", 10000, self.stamp, "https://example.test/fixture")


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(
        "app.services.option_search_service.get_ingredient_alias_approvals", lambda: {}
    )
    repo = Repositories()
    settings = SimpleNamespace(
        option_search_product_limit=42,
        option_search_work_limit=42,
        option_search_timeout_seconds=15,
        is_production=False,
    )
    return OptionSearchService(repo, repo, repo, settings), repo


def request(**changes):
    return OptionSearchRequest(category="lip", **changes)


@pytest.mark.anyio
@pytest.mark.parametrize("operator,group", [("includes", "ELIGIBLE"), ("excludes", "EXCLUDED")])
async def test_partial_positive_presence_and_same_option_intersection(setup, operator, group):
    service, _ = setup
    result = await service.search(
        request(
            ingredient_conditions=[{"ingredient_name": "Panthenol", "operator": operator}],
        )
    )
    assert {i.group for i in result.items} == {group}
    assert {i.option_id for i in result.items} == {"option-s1", "option-s2"}
    assert all(i.checks[-1].evidence_id and i.synthetic for i in result.items)
    assert "ingredients" not in result.model_dump_json()


@pytest.mark.anyio
async def test_absence_unsupported_and_current_price_remain_unknown(setup):
    service, repo = setup
    repo.option_price = AsyncMock(side_effect=AssertionError("Current price must skip snapshots"))
    result = await service.search(
        request(
            ingredient_conditions=[{"ingredient_name": "Fragrance", "operator": "excludes"}],
            maxPriceKRW=5000,
            price_basis="current_offer",
            fragrance_free=True,
            unsupported_conditions=["in stock"],
        )
    )
    assert result.status == "PARTIAL"
    assert all(i.group == "REFERENCE_ONLY" for i in result.items)
    assert all(
        c.verdict == "UNKNOWN" for i in result.items for c in i.checks if c.condition != "identity"
    )
    assert all(item.price is None for item in result.items)
    assert all(item.checks[-1].reason == "current_price_unverified" for item in result.items)
    repo.option_price.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("full", [False, True])
async def test_fragrance_free_rejects_verified_presence_and_never_promotes_absence(setup, full):
    service, repo = setup
    fragrance = IngredientIdentity(
        mfds_ingredient_id=1,
        name_ko="향료",
        source_hash="a" * 64,
        match_method="standard_name",
        rule_version="fixture-v1",
    )
    repo.name_matches["향료"] = OptionIngredientMatch(fragrance, "resolved")
    repo.entry_identity = fragrance.model_copy(
        update={"mfds_ingredient_id": 2, "name_ko": "판테놀", "source_hash": "b" * 64}
    )
    original_lookup = repo.lookup

    async def lookup(pid, sid):
        result = await original_lookup(pid, sid)
        if sid == "s1":
            result.evidence.ingredients[0].name = "향료"
            result.evidence.ingredients[0].identity = fragrance
        elif full:
            result.evidence.ingredient_coverage = "full"
            result.evidence.normalization_status = "verified"
        return result

    repo.lookup = lookup
    result = await service.search(request(fragrance_free=True))
    detected, unconfirmed = result.items
    assert detected.group == "EXCLUDED"
    check = detected.checks[-1]
    assert (check.condition, check.verdict, check.reason) == (
        "fragrance_free",
        "NOT_MATCH",
        "ingredient_present",
    )
    assert check.evidence_id and check.review_status == "verified"
    assert check.source_version == detected.source_version
    assert check.ingredient_coverage == "partial"
    assert unconfirmed.group == "REFERENCE_ONLY"
    assert unconfirmed.checks[-1].verdict == "UNKNOWN"
    assert unconfirmed.checks[-1].reason == (
        "fragrance_free_unverified" if full else "absence_not_verifiable"
    )
    assert not result.effective_request.ingredient_conditions
    assert repo.name_calls == ["향료"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "basis,group",
    [
        ("catalog_reference", "EXCLUDED"),
        ("collected_snapshot", "ELIGIBLE"),
        ("current_offer", "REFERENCE_ONLY"),
    ],
)
async def test_price_basis_cannot_be_substituted(setup, basis, group):
    service, _ = setup
    result = await service.search(request(maxPriceKRW=15000, price_basis=basis))
    assert {i.group for i in result.items} == {group}


@pytest.mark.anyio
async def test_snapshot_without_timezone_is_not_price_evidence(setup):
    service, repo = setup
    repo.stamp = None
    result = await service.search(request(maxPriceKRW=15000, price_basis="collected_snapshot"))
    assert all(i.checks[-1].verdict == "UNKNOWN" for i in result.items)


@pytest.mark.anyio
async def test_unmapped_and_production_synthetic_never_become_cards(setup):
    service, repo = setup
    repo.unmapped.add("s1")
    result = await service.search(request())
    assert result.checked_scope.unidentified_options == 1
    assert [i.shade_id for i in result.items] == ["s2"]
    service.settings.is_production = True
    result = await service.search(request())
    assert not result.items and not result.products and result.status == "PARTIAL"


@pytest.mark.anyio
async def test_null_shade_is_a_real_option_and_scope_is_exact(setup):
    service, repo = setup
    repo.products[0].shades = []
    req = request(
        product_ids=["fixture-product"],
        option_scope=[
            {"product_id": "fixture-product", "shade_id": None, "option_id": "option-None"}
        ],
    )
    result = await service.search(req)
    assert result.items[0].shade_id is None
    req.option_scope[0].option_id = "foreign-option"
    result = await service.search(req)
    assert not result.items and result.checked_scope.unidentified_options == 1


@pytest.mark.anyio
async def test_limits_report_partial_not_no_match(setup):
    service, repo = setup
    service.settings.option_search_work_limit = 1
    result = await service.search(request())
    assert result.checked_scope.stopped_reason == "WORK_LIMIT"
    assert result.checked_scope.checked_options == 1 and not result.checked_scope.exhaustive
    service.settings.option_search_work_limit = 42
    service.settings.option_search_product_limit = 1
    repo.products.append(make_product("other", "lip", []))
    result = await service.search(request())
    assert result.checked_scope.stopped_reason == "PRODUCT_LIMIT" and result.status == "PARTIAL"


@pytest.mark.anyio
@pytest.mark.parametrize("fragrance_free", [False, True])
async def test_timeout_retains_known_violation(setup, fragrance_free):
    service, repo = setup
    conditions = (
        [] if fragrance_free else [{"ingredient_name": "Panthenol", "operator": "excludes"}]
    )
    if fragrance_free:
        original_lookup = repo.lookup

        async def lookup(pid, sid):
            result = await original_lookup(pid, sid)
            result.evidence.ingredients[0].name = "향료"
            return result

        repo.lookup = lookup
    repo.slow = True
    service.settings.option_search_timeout_seconds = 0.01
    result = await service.search(
        request(
            ingredient_conditions=conditions,
            fragrance_free=fragrance_free,
            maxPriceKRW=10000,
        )
    )
    assert result.checked_scope.stopped_reason == "TIMEOUT"
    assert result.items[0].group == "EXCLUDED"
    assert [c.verdict for c in result.items[0].checks] == ["MATCH", "NOT_MATCH", "ERROR"]


@pytest.mark.anyio
async def test_entire_failure_is_error(setup):
    service, repo = setup
    repo.fail = True
    result = await service.search(request())
    assert result.status == "ERROR" and not result.products


@pytest.mark.anyio
async def test_duplicate_conditions_and_unknown_parameters_rejected(setup):
    service, _ = setup
    with pytest.raises(ApiError):
        await service.search(
            request(
                ingredient_conditions=[
                    {"ingredient_name": "Water", "operator": "includes"},
                    {"ingredient_name": " water ", "operator": "excludes"},
                ]
            )
        )
    with pytest.raises(ValidationError):
        OptionSearchRequest(category="lip", stock=True)
    with pytest.raises(ValidationError):
        OptionSearchRequest()
    with pytest.raises(ValidationError):
        OptionSearchRequest(query="   ")


def test_post_http_validation_and_rate_limit(setup):
    app = create_app()
    app.dependency_overrides[get_option_search_service] = lambda: setup[0]
    limiter = MemoryRateLimiter(1)
    app.dependency_overrides[get_option_search_rate_limiter] = lambda: limiter
    # Avoid app lifespan: the test must never start database/Redis connections.
    client = TestClient(app)
    response = client.post("/api/catalog/options/search", json={"category": "lip"})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["items"][0]["optionId"] == "option-s1"
    assert client.post("/api/catalog/options/search", json={"category": "lip"}).status_code == 429


@pytest.mark.anyio
async def test_display_budget_and_removed_option_scope_are_explicit(setup):
    service, repo = setup
    repo.products = [make_product(f"p-{i}", "lip", []) for i in range(7)]
    result = await service.search(request())
    assert len(result.products) == 6 and result.omitted_count == 1
    assert result.checked_scope.checked_options == 7
    result = await service.search(
        request(
            product_ids=["p-0"],
            option_scope=[{"product_id": "p-0", "shade_id": "deleted-shade", "option_id": "old"}],
        )
    )
    assert result.status == "PARTIAL" and not result.products
    assert result.checked_scope.unidentified_options == 1


@pytest.mark.anyio
async def test_real_repository_selects_are_bounded_read_only():
    from app.repositories.catalog_repository import CatalogRepository
    from app.repositories.oy_catalog_repository import OyCatalogRepository

    class Result:
        def all(self):
            return []

        def one_or_none(self):
            return None

    class Session:
        def __init__(self):
            self.statements = []

        async def scalar(self, stmt):
            self.statements.append(stmt)
            return 0

        async def scalars(self, stmt):
            self.statements.append(stmt)
            return Result()

        async def execute(self, stmt):
            self.statements.append(stmt)
            return Result()

    session = Session()
    assert await CatalogRepository(session).option_search_candidates(
        "Brand", "lip", ["p-1"], 3
    ) == ([], 0)
    assert session.statements[-1]._limit_clause.value == 3
    start = len(session.statements)
    assert await CatalogRepository(session).option_search_candidates(
        "", "base", None, 1, product_type="foundation"
    ) == ([], 0)
    for stmt in session.statements[start:]:
        sql = str(stmt)
        assert "raw_oy_product.std_category_code" in sql
        assert "raw_oy_category.category_name" in sql
        assert "raw_oy_product.delisted_at IS NULL" in sql
        assert "파운데이션" in stmt.compile().params.values()
    assert session.statements[-1]._limit_clause.value == 1
    assert await OyCatalogRepository(session).option_price("option-1", "oy-goods-1") is None
    assert all(stmt.is_select for stmt in session.statements)
    sql = str(session.statements[-1])
    assert "is_latest" in sql and "delisted_at IS NULL" in sql
    assert "goods_no =" in sql
    assert "GOODS-1" in session.statements[-1].compile().params.values()
    assert await OyCatalogRepository(session).product_texture("oy-goods-1") is None
    assert session.statements[-1].is_select
    assert "GOODS-1" in session.statements[-1].compile().params.values()


@pytest.mark.anyio
async def test_product_texture_is_not_option_evidence(setup):
    service, _ = setup
    result = await service.search(request(texture="matte"))
    assert all(i.group == "REFERENCE_ONLY" for i in result.items)
    assert all(i.checks[-1].reason == "option_texture_unverified" for i in result.items)


@pytest.mark.anyio
async def test_effective_request_and_evidence_metadata_survive_partial_result(setup):
    service, repo = setup
    req = request(ingredient_conditions=[{"ingredient_name": "Panthenol", "operator": "includes"}])
    result = await service.search(req)
    check = result.items[0].checks[-1]
    assert check.source_ref == "fixture://only" and check.observed_at == repo.stamp
    assert check.ingredient_coverage == "partial" and check.normalization_status == "unverified"
    assert check.review_status == "verified" and result.checked_at is not None
    assert result.items[0].ingredient_entry_count == 1
    assert result.items[0].ingredient_identity_count == 0
    repo.unmapped.update({"s1", "s2"})
    empty = await service.search(req)
    assert not empty.items and empty.effective_request == req


@pytest.mark.anyio
async def test_historical_date_is_unknown_even_with_latest_snapshot(setup):
    service, _ = setup
    result = await service.search(
        request(
            maxPriceKRW=15000,
            price_basis="collected_snapshot",
            unsupported_conditions=["2026-10-01 가격"],
        )
    )
    assert all(i.group == "REFERENCE_ONLY" for i in result.items)
    assert result.effective_request.unsupported_conditions == ["2026-10-01 가격"]


@pytest.mark.anyio
async def test_rights_limitation_does_not_block_existing_data(setup):
    service, _ = setup
    result = await service.search(request())
    assert result.items and "rights_unverified" in result.limitations


@pytest.mark.anyio
async def test_request_dependency_sets_read_only_snapshot_before_repositories(monkeypatch):
    from unittest.mock import AsyncMock

    from app.core.config import Settings

    settings = Settings()
    monkeypatch.setattr("app.services.option_search_service.get_settings", lambda: settings)
    session = AsyncMock()
    service = await get_option_search_service(session)
    assert str(session.execute.call_args.args[0]) == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert service.ingredients._session is session
    assert service.ingredients._pin_mapping


def test_mapping_is_pinned_only_for_g4(tmp_path):
    import json

    from app.repositories.ingredient_repository import IngredientRepository

    path = tmp_path / "mapping.json"
    path.write_text(json.dumps({"schemaVersion": 1, "records": []}), encoding="utf-8")
    pinned = IngredientRepository(None, mapping_path=path, pin_mapping=True)
    ordinary = IngredientRepository(None, mapping_path=path)
    assert pinned._mapping("p", None) is None
    path.write_text("invalid", encoding="utf-8")
    assert pinned._mapping("p", None) is None
    with pytest.raises(ApiError):
        ordinary._mapping("p", None)


@pytest.mark.anyio
async def test_mixed_groups_order_cards_without_erasing_excluded_options(setup):
    service, repo = setup
    repo.products = [
        make_product(pid, "lip", [(pid, pid, "#112233")])
        for pid in ("excluded", "unknown", "eligible")
    ]

    async def prices(option_id, product_id):
        if product_id == "unknown":
            raise SQLAlchemyError("one failed batch")
        amount = 50000 if product_id == "excluded" else 10000
        return (option_id, amount, repo.stamp, "fixture://price")

    repo.option_price = prices
    result = await service.search(request(maxPriceKRW=15000, price_basis="collected_snapshot"))
    assert result.status == "PARTIAL" and result.checked_scope.errors == 1
    assert result.excluded_count == 1
    assert [p.id for p in result.products] == ["eligible", "unknown"]
    assert {i.product_id: i.group for i in result.items} == {
        "excluded": "EXCLUDED",
        "unknown": "REFERENCE_ONLY",
        "eligible": "ELIGIBLE",
    }


@pytest.mark.anyio
async def test_naive_recorded_price_is_usable_without_inventing_a_timezone(setup):
    service, repo = setup

    # Keep ingredient evidence timestamps valid; only the price source is naive.
    async def price(option_id, product_id):
        return ("snapshot", 7600, datetime(2026, 10, 27, 17, 23, 57), "fixture://price")

    repo.option_price = price
    result = await service.search(request(maxPriceKRW=10000, price_basis="collected_snapshot"))
    for item in result.items:
        assert item.checks[-1].verdict == "MATCH"
        assert item.price.amount_krw == 7600
        assert item.price.observed_at is None
        assert item.price.observed_at_raw == datetime(2026, 10, 27, 17, 23, 57)
        assert item.price.limitations == ["timezone_unknown"]


@pytest.mark.anyio
async def test_missing_option_price_displays_reference_without_substituting_predicate(setup):
    service, repo = setup
    repo.option_price = AsyncMock(return_value=None)
    result = await service.search(request(maxPriceKRW=20000))
    assert result.effective_request.price_basis == "collected_snapshot"
    assert all(i.group == "REFERENCE_ONLY" for i in result.items)
    assert result.items[0].price.amount_krw == repo.products[0].price_krw
    assert result.items[0].price.observed_basis == "catalog_reference"
    assert result.items[0].checks[-1].reason == "option_price_unavailable"


@pytest.mark.anyio
@pytest.mark.parametrize("basis", ["product_name", "review_survey", "review_ai"])
async def test_texture_candidates_preserve_source_without_option_promotion(setup, basis):
    from unittest.mock import AsyncMock

    service, repo = setup
    repo.products.append(make_product("gloss", "lip", [], texture="glossy"))
    repo.product_texture = AsyncMock(return_value=("matte", basis, repo.stamp, "fixture://texture"))
    result = await service.search(request(texture="matte"))
    assert [p.id for p in result.products] == ["fixture-product"]
    assert result.checked_scope.candidate_options == 2
    assert all(i.group == "REFERENCE_ONLY" for i in result.items)
    assert all(i.checks[-1].texture_basis == basis for i in result.items)
    assert all(i.checks[-1].source_ref == "fixture://texture" for i in result.items)


@pytest.mark.anyio
@pytest.mark.parametrize("stale_price", [False, True])
async def test_reviewed_option_intersection_keeps_price_observation_bound_to_version(
    setup, stale_price
):
    service, repo = setup
    pid = repo.products[0].id
    present = IngredientIdentity(
        mfds_ingredient_id=123,
        name_ko="판테놀",
        source_hash="a" * 64,
        match_method="standard_name",
        rule_version="fixture-v1",
    )
    absent = present.model_copy(update={"mfds_ingredient_id": 456, "name_ko": "정제수"})
    repo.entry_identity = present
    repo.name_matches = {
        "판테놀": OptionIngredientMatch(present, "resolved"),
        "정제수": OptionIngredientMatch(absent, "resolved"),
    }
    price_stamp = datetime(2026, 10, 27, 17, 59, 38)
    price_source = "https://example.test/price"
    lookup = repo.lookup

    async def reviewed_lookup(product_id, shade_id):
        result = await lookup(product_id, shade_id)
        if shade_id == "s1":
            result.evidence.ingredient_coverage = "full"
            result.evidence.normalization_status = "verified"
            result.evidence.review_ref = "fixture://review"
            result.evidence.reviewed_at = repo.stamp
            result.option_review = ReviewedOptionEvidence(
                ingredient_identity_version="a" * 64,
                texture="matte",
                texture_source_ref="https://example.test/official",
                price_source_version=fingerprint(
                    ["option-s1", "v0" if stale_price else "v1", 12000, price_stamp, price_source]
                ),
                price_observed_at=price_stamp.replace(tzinfo=timezone(timedelta(hours=9))),
            )
        return result

    async def price(option_id, product_id):
        return ("v1", 12000, price_stamp, price_source)

    repo.lookup = reviewed_lookup
    repo.option_price = price
    result = await service.search(
        request(
            product_ids=[pid],
            texture="matte",
            maxPriceKRW=30000,
            ingredient_conditions=[
                {"ingredient_name": "판테놀", "operator": "includes"},
                {"ingredient_name": "정제수", "operator": "excludes"},
            ],
        )
    )
    reviewed, unreviewed = result.items
    assert reviewed.shade_id == "s1" and reviewed.group == "ELIGIBLE"
    assert all(check.verdict == "MATCH" for check in reviewed.checks)
    texture = next(check for check in reviewed.checks if check.condition == "texture")
    assert texture.texture_basis == "official_reviewed"
    assert texture.evidence_id == f"texture:option-s1:{texture.source_version}"
    assert texture.review_ref == "fixture://review"
    assert reviewed.price.observed_at_raw == (price_stamp if stale_price else None)
    assert reviewed.price.limitations == (["timezone_unknown"] if stale_price else [])
    if not stale_price:
        assert reviewed.price.observed_at.isoformat() == "2026-10-27T17:59:38+09:00"
    assert unreviewed.shade_id == "s2" and unreviewed.group == "REFERENCE_ONLY"
    assert (
        next(check for check in unreviewed.checks if check.condition == "texture").verdict
        == "UNKNOWN"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["판테놀", "판 테 놀", "Panthenol"])
async def test_canonical_name_is_resolved_once_and_preserves_request(setup, name):
    service, repo = setup
    canonical = IngredientIdentity(
        mfds_ingredient_id=123,
        name_ko="판테놀",
        source_hash="a" * 64,
        match_method="standard_name",
        rule_version="fixture-v1",
    )
    repo.entry_identity = canonical
    repo.name_matches[name] = OptionIngredientMatch(canonical, "resolved")
    result = await service.search(
        request(
            ingredient_conditions=[
                {"ingredientName": name, "operator": "excludes"},
            ]
        )
    )
    assert repo.name_calls == [name]
    assert result.ingredient_resolutions[0].canonical_name == "판테놀"
    assert result.effective_request.ingredient_conditions[0].ingredient_name == name
    assert len(result.items) == 2
    assert all(
        i.group == "EXCLUDED" and i.checks[-1].reason == "ingredient_present" for i in result.items
    )
    assert all(i.checks[-1].ingredient_name == name for i in result.items)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name,status", [("미네랄오잉", "unresolved"), ("실리콘 오일 성분군", "unsupported_group")]
)
async def test_requires_name_confirmation_before_product_scan(setup, name, status):
    service, repo = setup
    repo.fail = True
    repo.name_matches["미네랄오잉"] = OptionIngredientMatch(
        status="unresolved",
        suggestions=("미네랄오일",),
    )
    result = await service.search(
        request(
            ingredient_conditions=[
                {"ingredientName": name, "operator": "excludes"},
            ]
        )
    )
    assert result.status == "PARTIAL" and not result.items
    assert result.checked_scope.stopped_reason == "INGREDIENT_CONFIRMATION"
    assert result.checked_scope.candidate_products == 0
    assert result.ingredient_resolutions[0].status == status


@pytest.mark.anyio
async def test_opposite_operators_using_two_spellings_require_confirmation(setup):
    service, repo = setup
    canonical = IngredientIdentity(
        mfds_ingredient_id=317,
        name_ko="미네랄오일",
        source_hash="a" * 64,
        match_method="standard_name",
        rule_version="fixture-v1",
    )
    for name in ("미네랄오일", "미네랄 오일"):
        repo.name_matches[name] = OptionIngredientMatch(canonical, "resolved")
    result = await service.search(
        request(
            ingredient_conditions=[
                {"ingredientName": "미네랄오일", "operator": "includes"},
                {"ingredientName": "미네랄 오일", "operator": "excludes"},
            ]
        )
    )
    assert result.checked_scope.stopped_reason == "INGREDIENT_CONFIRMATION"
    assert [r.status for r in result.ingredient_resolutions] == ["conflict", "conflict"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,expected", [("foundation", "pure-foundation"), ("cushion", "cushion-name")]
)
async def test_base_type_uses_both_classifications_before_limit(setup, kind, expected):
    service, repo = setup
    repo.products = [
        make_product("conflict", "base", []),
        make_product("missing", "base", []),
        make_product("cushion-name", "base", []),
        make_product("pure-foundation", "base", []),
    ]
    repo.products[2].name = "쿠션 파운데이션"
    repo.products[3].name = "색조 커버"
    repo.product_types = {
        "conflict": ("foundation", "cushion"),
        "missing": ("foundation", None),
        "cushion-name": ("cushion", "cushion"),
        "pure-foundation": ("foundation", "foundation"),
    }
    service.settings.option_search_product_limit = 1
    req = OptionSearchRequest(category="base", productType=kind)
    result = await service.search(req)
    assert result.effective_request == req
    assert result.checked_scope.candidate_products == 1
    assert [(i.product_id, i.product_type) for i in result.items] == [(expected, kind)]


def test_base_product_type_cannot_attach_to_another_category():
    with pytest.raises(ValidationError):
        OptionSearchRequest(category="lip", productType="foundation")


@pytest.mark.anyio
@pytest.mark.parametrize("query,expected", [("", "reviewed"), ("fixture", "fixture-product")])
async def test_reviewed_texture_can_enter_bounded_search_without_bypassing_query(
    setup, query, expected
):
    service, repo = setup
    repo.products = [
        make_product(pid, "lip", [("s1", "01", "#112233")]).model_copy(update={"texture": "matte"})
        for pid in ("fixture-product", "fixture-other", "reviewed")
    ]
    repo.reviewed_texture_keys = {("reviewed", "s1")}
    service.settings.option_search_product_limit = 1
    result = await service.search(
        request(
            query=query,
            texture="matte",
            ingredient_conditions=[{"ingredient_name": "Panthenol", "operator": "includes"}],
        )
    )
    assert repo.lookup_calls == [(expected, "s1")]
    assert result.checked_scope.candidate_products == (2 if query else 3)
    assert result.checked_scope.candidate_options == 1
    assert result.checked_scope.stopped_reason == "PRODUCT_LIMIT"
    assert result.items[0].group == "REFERENCE_ONLY"  # A priority hint is never proof.


@pytest.mark.anyio
async def test_reviewed_options_move_ahead_of_unmapped_but_keep_relative_order(setup):
    service, repo = setup
    repo.products = [
        make_product("first", "base", [("unmapped", "01", "#112233")]),
        make_product("mapped", "base", [("s2", "02", "#112233"), ("s1", "01", "#334455")]),
    ]
    repo.product_types = {p.id: ("foundation", "foundation") for p in repo.products}
    repo.unmapped = {"unmapped"}
    repo.priority = {("mapped", "s1"), ("mapped", "s2")}
    service.settings.option_search_work_limit = 4
    result = await service.search(
        OptionSearchRequest(
            category="base",
            productType="foundation",
            ingredientConditions=[{"ingredientName": "Fragrance", "operator": "excludes"}],
        )
    )
    assert repo.lookup_calls == [("mapped", "s2"), ("mapped", "s1")]
    assert result.checked_scope.candidate_options == 3
    assert (
        result.checked_scope.checked_options == 2 and result.checked_scope.unidentified_options == 0
    )
    assert (
        result.checked_scope.stopped_reason == "WORK_LIMIT" and not result.checked_scope.exhaustive
    )
    assert [(i.shade_id, i.group, i.product_type) for i in result.items] == [
        ("s2", "REFERENCE_ONLY", "foundation"),
        ("s1", "REFERENCE_ONLY", "foundation"),
    ]
    assert all(i.checks[-1].reason == "absence_not_verifiable" for i in result.items)


@pytest.mark.anyio
@pytest.mark.parametrize("explicit,ingredient", [(True, True), (False, False)])
async def test_explicit_scope_and_noningredient_search_keep_original_order(
    setup, explicit, ingredient
):
    service, repo = setup
    repo.unmapped = {"s1"}
    repo.priority = {("fixture-product", "s2")}
    service.settings.option_search_work_limit = 2 if ingredient else 1
    scope = [
        {"productId": "fixture-product", "shadeId": s, "optionId": f"option-{s}"}
        for s in ("s1", "s2")
    ]
    result = await service.search(
        request(
            product_ids=["fixture-product"] if explicit else None,
            option_scope=scope if explicit else None,
            ingredient_conditions=(
                [{"ingredientName": "Fragrance", "operator": "excludes"}] if ingredient else []
            ),
        )
    )
    assert repo.lookup_calls == [("fixture-product", "s1")]
    assert result.checked_scope.unidentified_options == 1 and not result.items


def test_ordering_hints_share_pinned_mapping_and_skip_ambiguous_or_unreviewed_records(tmp_path):
    import json

    from app.repositories.ingredient_repository import IngredientRepository

    valid = IngredientMapping(
        product_id="oy-product",
        shade_id="current",
        option_id="source-option",
        goods_no="PRODUCT",
        catalog_fingerprint="catalog-snapshot",
        mapping_status="directly_reviewed",
        mapping_method="direct_review",
        review_status="verified",
        source_version="snapshot-1",
    )
    duplicate = valid.model_copy(update={"shade_id": "duplicate"})
    other = duplicate.model_copy(update={"option_id": "other-source-option"})
    unreviewed = valid.model_copy(update={"shade_id": "unreviewed", "review_status": "unreviewed"})
    records = [valid, duplicate, other, unreviewed]
    path = tmp_path / "mapping.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "records": [r.model_dump(mode="json", by_alias=True) for r in records],
            }
        ),
        encoding="utf-8",
    )
    repo = IngredientRepository(None, mapping_path=path, pin_mapping=True)
    assert repo.prioritized_option_keys({("oy-product", r.shade_id) for r in records}) == {
        ("oy-product", "current")
    }
    path.write_text("invalid", encoding="utf-8")
    assert repo._mapping("oy-product", "current").option_id == "source-option"
    with pytest.raises(ApiError, match="Duplicate ingredient mapping"):
        repo._mapping("oy-product", "duplicate")


@pytest.mark.anyio
async def test_priority_hint_cannot_override_catalog_version_failure(setup, monkeypatch):
    service, repo = setup
    repo.priority = {("fixture-product", "s2")}
    service.settings.option_search_work_limit = 2

    async def stale(pid, sid):
        repo.lookup_calls.append((pid, sid))
        return IngredientReadResult(
            product_id=pid,
            shade_id=sid,
            mapping_status="mismatch",
            reason="catalog_version_mismatch",
        )

    monkeypatch.setattr(repo, "lookup", stale)
    result = await service.search(
        request(
            ingredient_conditions=[
                {"ingredientName": "Panthenol", "operator": "includes"},
            ]
        )
    )
    assert repo.lookup_calls == [("fixture-product", "s2")]
    assert result.checked_scope.unidentified_options == 1
    assert not result.items and not result.products and result.status == "PARTIAL"
