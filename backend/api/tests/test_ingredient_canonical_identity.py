"""Synthetic identities and SQL sessions, independent from operating product data."""

import pytest
from pydantic import ValidationError

from app.repositories.ingredient_identity_repository import IngredientIdentityRepository
from app.repositories.ingredient_repository import catalog_fingerprint
from app.schemas.ingredient import IngredientEntry, IngredientIdentity, IngredientLookupResult
from app.services.ingredient_service import evaluate_ingredient
from tests.test_ingredient_api import Session, get, setup
from tests.test_ingredient_api import data as data
from tests.test_ingredient_service import condition
from tests.test_ingredient_service import evidence as evidence


@pytest.fixture
def anyio_backend():
    return "asyncio"


def identity(number, **changes):
    return IngredientIdentity(
        mfds_ingredient_id=number,
        name_ko=f"standard-{number}",
        source_hash="a" * 64,
        match_method="exact_name",
        rule_version="fixture-v1",
        **changes,
    )


def row(number, oy=101, **changes):
    values = dict(method="exact_name", rule="fixture-v1", reviewer=None, stamp=None)
    values.update(changes)
    return (
        number,
        f"standard-{number}",
        "a" * 64,
        oy,
        values["method"],
        values["rule"],
        values["reviewer"],
        values["stamp"],
        f"standard-{number}",
        f"english-{number}",
        f"alias-{number}",
    )


@pytest.mark.parametrize("operator,expected", [("includes", "MATCH"), ("excludes", "NOT_MATCH")])
def test_alias_presence_uses_identity_and_preserves_raw_name(evidence, operator, expected):
    evidence.ingredients[1].identity = identity(82)
    result = evaluate_ingredient(
        condition("unrelated official spelling", operator),
        IngredientLookupResult(status="ok", evidence=evidence),
        identity(82),
    )
    assert result.verdict == expected
    assert evidence.ingredients[1].name == "Panthenol"
    assert result.query_identity.mfds_ingredient_id == 82


@pytest.mark.parametrize("operator,expected", [("includes", "NOT_MATCH"), ("excludes", "MATCH")])
def test_absence_requires_every_entry_identity(evidence, operator, expected):
    for index, item in enumerate(evidence.ingredients):
        item.identity = identity(index + 1)
    lookup = IngredientLookupResult(status="ok", evidence=evidence)
    assert (
        evaluate_ingredient(condition("different", operator), lookup, identity(82)).verdict
        == expected
    )
    evidence.ingredients[0].identity = None
    assert (
        evaluate_ingredient(condition("different", operator), lookup, identity(82)).verdict
        == "UNKNOWN"
    )


def test_same_id_different_snapshot_cannot_be_absence(evidence):
    evidence.ingredients = [IngredientEntry(name="other", sequence=1, identity=identity(82))]
    query = identity(82).model_copy(update={"source_hash": "b" * 64})
    result = evaluate_ingredient(
        condition("different", "excludes"),
        IngredientLookupResult(status="ok", evidence=evidence),
        query,
    )
    assert (result.verdict, result.reason) == ("UNKNOWN", "ingredient_identity_version_mismatch")


@pytest.mark.anyio
async def test_current_identity_select_is_read_only_and_ignores_invalid_provenance():
    session = Session(
        [
            [row(82), row(83, oy=102, method="manual")],
            [(82, "standard-82", "english-82", "alias-82")],
        ]
    )
    found = await IngredientIdentityRepository(session).for_entries([101, 102])
    assert set(found) == {101}
    assert "is_current IS true" in str(session.statements[0])
    assert "oy_mfds_ingredient_map" in str(session.statements[0])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "rows", [[], [row(82) + (False, False, False), row(83) + (False, False, False)]]
)
async def test_query_missing_or_ambiguous_identity_stays_unresolved(rows):
    assert await IngredientIdentityRepository(Session([rows])).resolve("unknown") is None


@pytest.mark.anyio
async def test_official_query_can_resolve_without_oliveyoung_mapping():
    session = Session([[row(82, oy=None, method=None, rule=None) + (False, True, True)]])
    found = await IngredientIdentityRepository(session).resolve("Official English Name")
    assert found.mfds_ingredient_id == 82 and found.match_method == "english_name"


def test_manual_identity_cannot_be_asserted_without_review():
    with pytest.raises(ValidationError):
        IngredientIdentity(
            mfdsIngredientId=82, nameKo="standard", sourceHash="a" * 64, matchMethod="manual"
        )


def test_colorless_product_uses_reviewed_option_without_inventing_shade(client, data):
    product, _, raw, entries, mapping = data
    mapping.shade_id = None
    mapping.catalog_fingerprint = catalog_fingerprint(*product, [])
    setup(client, (product, [], raw, entries, mapping))
    body = client.get(
        "/api/products/oy-fixture/ingredients", params={"ingredientName": "Panthenol"}
    ).json()
    assert body["shadeId"] is None and body["optionId"] == mapping.option_id
    assert body["verdict"] == "MATCH"


def test_api_to_canonical_ids_including_query_and_original_text(client, data):
    product, shades, raw, entries, _ = data
    session = setup(
        client,
        data,
        [
            [product],
            shades,
            [raw],
            entries,
            [row(1, oy=1), row(2, oy=2)],
            [(1, "standard-1", "english-1", "alias-1"), (2, "standard-2", "english-2", "alias-2")],
            [row(2, oy=2) + (False, True, True)],
        ],
    )
    body = get(client, ingredientName="official alias").json()
    assert body["verdict"] == "MATCH"
    assert body["ingredients"][1]["name"] == "Panthenol"
    assert body["ingredients"][1]["identity"]["mfdsIngredientId"] == 2
    assert body["conditions"][0]["queryIdentity"]["mfdsIngredientId"] == 2
    assert len(session.statements) == 7


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,raw_name",
    [
        ("official_synonym", "removed alias"),
        ("amount_suffix_exact", "different(10ppm)"),
        ("manual", "standard-82"),
    ],
)
async def test_stale_links_and_unversioned_manual_reviews_do_not_gain_current_hash(
    method, raw_name
):
    old = list(row(82, method=method, reviewer="Reviewer", stamp="2026-01-01T00:00:00Z"))
    old[8] = raw_name
    assert await IngredientIdentityRepository(Session([[tuple(old)]])).for_entries([101]) == {}


@pytest.mark.anyio
async def test_new_competing_synonym_invalidates_previously_unique_link():
    current = list(row(82, method="official_synonym"))
    current[8] = "alias-82"
    session = Session(
        [
            [tuple(current)],
            [
                (82, "standard-82", "english-82", "alias-82"),
                (83, "standard-83", "english-83", "alias-82"),
            ],
        ]
    )
    assert await IngredientIdentityRepository(session).for_entries([101]) == {}


@pytest.mark.anyio
@pytest.mark.parametrize("competing", [True, False])
async def test_amount_alias_query_rechecks_current_base_identity_before_absence(
    competing, evidence
):
    mapped = list(row(82, method="amount_suffix_synonym"))
    mapped[8] = "alias-82(10ppm)"
    standards = [(82, "standard-82", "english-82", "alias-82")]
    if competing:
        standards.append((83, "standard-83", "english-83", "alias-82"))
    session = Session([[tuple(mapped) + (False, False, False)], [tuple(mapped)], standards])
    query = await IngredientIdentityRepository(session).resolve("alias-82(10ppm)")
    evidence.ingredients = [IngredientEntry(name="standard-83", sequence=1, identity=identity(83))]
    check = evaluate_ingredient(
        condition("alias-82(10ppm)", "excludes"),
        IngredientLookupResult(status="ok", evidence=evidence),
        query,
    )
    assert check.verdict == ("UNKNOWN" if competing else "MATCH")


@pytest.mark.anyio
async def test_api_resolve_rejects_unreviewed_split_alias(monkeypatch):
    from app.repositories import ingredient_identity_repository as repository

    monkeypatch.setattr(repository, "_approvals", lambda: frozenset())
    original = list(row(82, oy=None, method=None, rule=None))
    original[10] = "코코아버터,카카오씨드버터"
    session = Session([[tuple(original) + (False, False, True)]])
    assert await IngredientIdentityRepository(session).resolve("코코아버터") is None


@pytest.mark.anyio
async def test_api_resolve_accepts_approved_split_alias(monkeypatch):
    from app.repositories import ingredient_identity_repository as repository

    monkeypatch.setattr(
        repository,
        "_approvals",
        lambda: frozenset({(82, "코코아버터", "a" * 64)}),
    )
    original = list(row(82, oy=None, method=None, rule=None))
    original[10] = "코코아버터,카카오씨드버터"
    session = Session([[tuple(original) + (False, False, True)]])
    found = await IngredientIdentityRepository(session).resolve("코코아버터")
    assert found is not None and found.mfds_ingredient_id == 82
    assert found.match_method == "official_synonym"
