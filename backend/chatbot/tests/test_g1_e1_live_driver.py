"""Boundary checks for the E1 driver; these tests do not stand in for live runs."""

import asyncio

from tests.g1_e1_live_driver import (
    FixtureModel,
    catalog_rows_match_db,
    product_identity_matches,
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
