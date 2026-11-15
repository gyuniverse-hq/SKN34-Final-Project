"""Boundary checks for the E1 driver; these tests do not stand in for live runs."""

import asyncio

from tests.g1_e1_live_driver import (
    FixtureModel,
    catalog_rows_match_db,
    detail_ownership_matches,
    detail_response_failure,
    product_identity_matches,
    response_shade_pairs,
    run,
)


def test_product_identity_must_match_read_only_database_rows():
    product = {"id": "p", "brand": "brand", "category": "lip"}
    assert product_identity_matches([product], [product])
    assert not product_identity_matches([product], [])
    assert not product_identity_matches([product], [product | {"brand": "other"}])
    assert not product_identity_matches([product], [product | {"category": "eye"}])


def test_fixture_plan_explicitly_uses_case_arguments():
    model = FixtureModel({"expected": {"allowedArgs": {"q": "브랜드", "category": "lip"}}})
    assert model.arguments == {"category": "lip", "query": "브랜드"}
    detail = FixtureModel({"caseId": "G1-CAT-12", "expected": {"allowedArgs": {}}})
    assert detail.detail and detail.arguments == {"intent": "detail"}


def test_detail_fixture_needs_two_real_distinct_product_shade_owners():
    fixture = {"productId": "a", "foreignProductId": "b", "shadeId": "a1", "foreignShadeId": "b1"}
    db = {
        "products": [{"id": "a"}, {"id": "b"}],
        "shades": [
            {"product_id": "a", "id": "a1"},
            {"product_id": "b", "id": "b1"},
        ],
    }
    assert detail_ownership_matches(fixture, db)
    assert not detail_ownership_matches(fixture, db | {"products": [{"id": "a"}]})
    assert not detail_ownership_matches(
        fixture, db | {"shades": db["shades"] + [{"product_id": "a", "id": "b1"}]}
    )
    assert not detail_ownership_matches(fixture, db | {"shades": [{"product_id": "a", "id": "a1"}]})


def test_detail_response_shade_pairs_come_from_measured_selection():
    assert response_shade_pairs({"chatContext": {"shadeSelections": {}}}) == []
    assert response_shade_pairs({"chatContext": {"shadeSelections": {"a": "wrong"}}}) == [
        {"productId": "a", "shadeId": "wrong"}
    ]
    assert response_shade_pairs({"ingredientResults": [{"productId": "a", "shadeId": "s"}]}) == [
        {"productId": "a", "shadeId": "s"}
    ]


def test_detail_response_rejects_invalid_or_fabricated_results():
    fixture = {"foreignShadeName": "foreign-shade"}
    clarify = {
        "answer": "상품과 색상을 다시 선택해 주세요",
        "products": [],
        "resultType": "clarification",
    }
    empty = {"answer": "상품을 찾을 수 없어요", "products": [], "resultType": "empty"}
    assert detail_response_failure("G1-CAT-12", clarify, fixture) is None
    assert detail_response_failure("G1-CAT-11", empty, fixture) is None
    assert (
        detail_response_failure("G1-CAT-12", clarify | {"answer": " "}, fixture)
        == "empty_chat_response"
    )
    assert detail_response_failure("G1-CAT-12", clarify | {"answer": "foreign-shade"}, fixture)
    assert detail_response_failure("G1-CAT-12", clarify | {"resultType": "empty"}, fixture)
    assert detail_response_failure("G1-CAT-12", {"answer": "missing products"}, fixture)
    context = {
        "issuedAt": 0,
        "filters": {},
        "candidateIds": ["a"],
        "scopeIds": ["a"],
        "selectedProductId": "a",
        "shadeSelections": {"a": "b"},
    }
    assert detail_response_failure("G1-CAT-12", clarify | {"chatContext": context}, fixture)
    fake = {"id": "fake", "brand": "B", "name": "N", "category": "lip"}
    assert detail_response_failure("G1-CAT-11", empty | {"products": [fake]}, fixture)


def test_returned_catalog_rows_match_all_db_fields_and_owned_shades():
    db = {
        "id": "p",
        "brand": "brand",
        "name": "name",
        "name_ko": "이름",
        "category": "lip",
        "price_krw": 10,
    }
    shade = {"product_id": "p", "id": "1", "name": "shade", "hex": "#123456"}
    api = {
        "id": "p",
        "brand": "brand",
        "name": "name",
        "nameKo": "이름",
        "category": "lip",
        "priceKRW": 10,
        "shades": [{"id": "1", "name": "shade", "hex": "#123456"}],
    }
    assert catalog_rows_match_db(["p"], [api], [db], [shade])
    assert not catalog_rows_match_db(["p"], [api | {"priceKRW": 11}], [db], [shade])
    assert not catalog_rows_match_db(["p"], [api | {"nameKo": "다름"}], [db], [shade])
    assert not catalog_rows_match_db(["p"], [api | {"shades": []}], [db], [shade])
    assert not catalog_rows_match_db(["p"], [api], [db], [shade | {"product_id": "other"}])


def test_unsupported_case_never_invents_observation():
    item = {
        "case": {"caseId": "G1-REG-07", "caseRevision": 1},
        "variantId": "default",
        "runId": "test",
    }
    result = asyncio.run(run(item))
    assert result["observation"]["status"] == "NOT_RUN"
    assert result["artifacts"] == {}
