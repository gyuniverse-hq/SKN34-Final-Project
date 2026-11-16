"""Boundary checks for the E1 driver; these tests do not stand in for live runs."""

import asyncio
import json

import pytest

from tests.g1_e1_live_driver import (
    FixtureModel,
    catalog_rows_match_db,
    detail_answer_shade_pairs,
    detail_ownership_matches,
    detail_response_failure,
    observe_known_limitations,
    observe_reg07,
    product_identity_matches,
    response_shade_pairs,
    run,
)


@pytest.mark.parametrize(
    "case_id,answer",
    [
        ("G1-CAT-13", "검수된 전성분이 없어 해당 성분이나 알레르기 안전 여부는 확인할 수 없어요."),
        (
            "G1-CAT-10",
            "현재 카탈로그에서 조건에 맞는 후보 1개를 찾았어요. "
            "표시 순서의 번호로 후속 질문을 할 수 있어요. "
            "가격은 상품 기준가격이며 판매처·옵션에 따라 달라질 수 있어요.",
        ),
    ],
)
def test_known_limitations_require_whole_answer_and_evidence(case_id, answer):
    payload = {"answer": answer, "products": [{"id": "p"}]}
    observed = observe_known_limitations(case_id, payload, "run/response.json")
    assert observed["claimAudit"]["complete"] is True
    assert observed["claimAudit"]["claims"]
    assert " ".join(c["text"] for c in observed["claimAudit"]["claims"]) == answer
    assert all(c["verification"] != "VERIFIED" for c in observed["claimAudit"]["claims"])
    for changed in (
        "",
        answer + " 무향료 제품입니다.",
        answer + " 현재 판매가입니다.",
        answer.replace("확인할 수 없어요", "확인했어요") + "추가",
    ):
        assert (
            observe_known_limitations(case_id, payload | {"answer": changed}, "run/response.json")
            == {}
        )
    assert observe_known_limitations(case_id, payload, "") == {}
    assert observe_known_limitations(case_id, {"answer": answer}, "run/response.json") == {}


def test_product_identity_must_match_read_only_database_rows():
    product = {"id": "p", "brand": "brand", "category": "lip"}
    assert product_identity_matches([product], [product])
    assert not product_identity_matches([product], [])
    assert not product_identity_matches([product], [product | {"brand": "other"}])
    assert not product_identity_matches([product], [product | {"category": "eye"}])


def test_price_limitations_need_the_same_product_and_reference_price():
    source = {"id": "p", "brand": "브랜드", "name": "제품", "priceKRW": 12000}
    payload = {
        "products": [{"id": "p"}],
        "answer": "브랜드 제품\nCatalog 기준가격: 12,000원.\n"
        "오늘의 실제 판매가·판매처·확인 시각은 미확인입니다. "
        "가격 원본 출처와 검수 상태는 미확인입니다.",
    }
    assert observe_known_limitations("G1-CAT-06", payload, "r/response.json", [source])[
        "claimAudit"
    ]["complete"]
    assert observe_known_limitations("G1-CAT-06", payload, "r/response.json", []) == {}
    assert (
        observe_known_limitations(
            "G1-CAT-06", payload, "r/response.json", [source | {"id": "other"}]
        )
        == {}
    )
    assert (
        observe_known_limitations(
            "G1-CAT-06", payload, "r/response.json", [source | {"priceKRW": 13000}]
        )
        == {}
    )
    assert (
        observe_known_limitations(
            "G1-CAT-06",
            payload | {"answer": payload["answer"] + " 오늘 할인 중입니다."},
            "r/response.json",
            [source],
        )
        == {}
    )


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


def test_catalog_difference_preserves_missing_fields_and_hides_values():
    from tests.g1_e1_live_driver import catalog_row_difference

    result = catalog_row_difference(
        {"id": "p", "priceKRW": 100, "extra": "private-value"},
        {"id": "p", "priceKRW": 200, "nullable": None},
    )
    assert result["productId"] == "p"
    assert [field["field"] for field in result["fields"]] == ["extra", "nullable", "priceKRW"]
    assert "private-value" not in json.dumps(result)
    assert catalog_row_difference({"id": "p"}, {"id": "p"})["fields"] == []
