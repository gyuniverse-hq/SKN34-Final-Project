"""Boundary checks for the E1 driver; these tests do not stand in for live runs."""

import asyncio
import json

from tests.g1_e1_live_driver import (
    FixtureModel,
    catalog_rows_match_db,
    detail_answer_shade_pairs,
    detail_ownership_matches,
    detail_response_failure,
    observe_reg07,
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


def test_case_plans_keep_search_constraints_and_detail_scope():
    for case_id in ("G1-CAT-04", "G1-CAT-13"):
        detail = FixtureModel({"caseId": case_id, "expected": {"allowedArgs": {}}})
        assert detail.detail and detail.arguments == {"intent": "detail"}
    price = FixtureModel({"caseId": "G1-CAT-06", "expected": {"allowedArgs": {}}})
    assert price.detail and price.arguments == {"intent": "price"}
    search = FixtureModel(
        {
            "caseId": "G1-CAT-02",
            "expected": {
                "allowedArgs": {
                    "category": "lip",
                    "internalIntent.maxPriceKRW": 20000,
                    "internalIntent.moisturizing": True,
                }
            },
        }
    )
    assert search.arguments == {"category": "lip", "maxPriceKRW": 20000, "moisturizing": True}
    fragrance = FixtureModel(
        {
            "caseId": "G1-CAT-05",
            "expected": {
                "allowedArgs": {
                    "category": "lip",
                    "internalIntent.fragranceFree": True,
                }
            },
        }
    )
    assert fragrance.arguments == {"category": "lip", "fragrance_free": True}


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


def test_answer_shades_are_complete_and_unambiguously_bound_to_db():
    shades = [
        {"product_id": "a", "id": "a1", "name": "레몬"},
        {"product_id": "a", "id": "a2", "name": "딸기"},
        {"product_id": "b", "id": "b1", "name": "체리"},
    ]
    answer = {"answer": "상품의 확인된 색상: 레몬, 딸기"}
    assert detail_answer_shade_pairs(answer, "a", shades) == (
        [{"productId": "a", "shadeId": "a1"}, {"productId": "a", "shadeId": "a2"}],
        None,
    )
    assert detail_answer_shade_pairs({"answer": "색상: 레몬, 딸기"}, "a", shades) == (None, None)
    assert detail_answer_shade_pairs({"answer": "확인된 색상: 레몬"}, "a", shades) == (None, None)
    assert detail_answer_shade_pairs({"answer": "확인된 색상: 레몬, 체리"}, "a", shades) == (
        None,
        "foreign_shade_name",
    )
    assert detail_answer_shade_pairs({"answer": "확인된 색상: 레몬, 포도"}, "a", shades) == (
        None,
        None,
    )
    assert detail_answer_shade_pairs(
        answer, "a", shades + [{"product_id": "a", "id": "a3", "name": "딸기"}]
    ) == (None, None)


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
        "case": {"caseId": "G1-NOT-IMPLEMENTED", "caseRevision": 1},
        "variantId": "default",
        "runId": "test",
    }
    result = asyncio.run(run(item))
    assert result["observation"]["status"] == "NOT_RUN"
    assert result["artifacts"] == {}


def test_reg07_records_distinct_actual_requests_without_baseline_or_secrets():
    from app.core import auth
    from app.core.config import get_settings
    from tests.test_chat_sessions import SessionCatalog

    case = {
        "caseId": "G1-REG-07",
        "input": {"message": "립 제품 추천해줘", "locale": "ko", "requestType": "chat"},
        "expected": {"allowedArgs": {"category": "lip"}},
    }
    old_verifier = auth.get_verifier
    old_flag = get_settings().g1_supervisor_enabled
    result = asyncio.run(observe_reg07(case, "a" * 32, SessionCatalog(), "trace"))
    authorized = result["securityObservations"]["authorized"]
    foreign = result["securityObservations"]["foreignSession"]
    assert authorized["httpStatus"] == 200
    assert authorized["response"] == result["response"]
    assert authorized["request"] == result["request"]
    assert foreign["httpStatus"] == 403
    assert foreign["requestId"] != authorized["requestId"]
    assert foreign["session"]["fixtureActive"] is True
    assert foreign["trace"]["completeDomains"] == ["tools"]
    assert foreign["response"]["code"] == "chat_session_forbidden"
    assert foreign["claimAudit"]["complete"] is True
    assert "baselineResults" not in result["auth"]
    assert [step["status"] for step in result["steps"]] == [200, 200, 200, 403]
    assert "sessionToken" not in json.dumps(result)
    assert "g1-fixture-user" not in json.dumps(result)
    assert result["fixtureIdentity"]["sessionStore"] == "RedisDouble fixture"
    assert auth.get_verifier is old_verifier
    assert get_settings().g1_supervisor_enabled == old_flag
