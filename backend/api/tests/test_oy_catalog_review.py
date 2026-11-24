"""Regression tests for the append-only catalog review policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.schemas.catalog import Product

SCRIPT = Path(__file__).resolve().with_name("build_catalog_review.py")
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data/oliveyoung/build_catalog_review.py"
spec = importlib.util.spec_from_file_location("oy_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def product(gid):
    return {
        "id": "oy-" + gid.lower(),
        "brand": "브랜드",
        "name": "상품",
        "nameKo": "상품",
        "category": "base",
        "makeupZone": None,
        "texture": "cream",
        "priceKRW": 10000,
        "volume": "30ml",
        "shades": [],
        "description": "",
        "keyIngredients": [],
        "tags": ["oliveyoung", "BB/CC"],
        "imageUrl": "https://example.com/item.png",
        "searchKeyword": "상품",
    }


def raw(gid, code="BB/CC", served=False, display="BB/CC"):
    return {
        "goods_no": gid,
        "std_category_code": code,
        "category_name": display,
        "is_in_catalog": served,
        "delisted_at": None,
        "sale_status": "정상",
    }


def approved(gid):
    return {
        "goodsNo": gid,
        "sourceStandardCategory": "BB/CC",
        "displayCategory": "BB/CC",
        "reviewedCategory": "BB/CC",
        "servingCategory": "base",
        "decision": "include",
        "texture": "cream",
        "makeupZone": None,
    }


def test_new_unreviewed_no_automatic_insert_and_existing_preserved():
    p = product("A1")
    seed = {"products": [p], "looks": [], "stores": []}
    result, rows = review.reconcile(
        seed,
        {p["id"]: Product.model_validate(p)},
        [raw("A1", served=True), raw("A2")],
        {},
        lambda *_: pytest.fail("unapproved candidate"),
        lambda _: None,
    )
    assert result == seed
    assert [r["decision"] for r in rows] == [
        "preserve_existing",
        "manual_review_required",
    ]


def test_reviewed_exclusion_and_explicit_append():
    exclude = {
        "sourceStandardCategory": "키링/인형",
        "displayCategory": "립스틱",
        "decision": "exclude",
    }
    result, rows = review.reconcile(
        {"products": [], "looks": [], "stores": []},
        {},
        [raw("A1"), raw("A2", "키링/인형", display="립스틱")],
        {"A1": approved("A1"), "A2": exclude},
        lambda *_: product("A1"),
        lambda _: None,
    )
    assert result["products"] == [product("A1")]
    assert [r["decision"] for r in rows] == ["append_reviewed_candidate", "exclude"]


def test_refuses_seed_live_drift():
    p = product("A1")
    seed = {"products": [p], "looks": [], "stores": []}
    with pytest.raises(ValueError, match="fields differ"):
        review.reconcile(
            seed,
            {p["id"]: Product.model_validate({**p, "priceKRW": 20000})},
            [raw("A1", served=True)],
            {},
            lambda *_: None,
            lambda _: None,
        )


def test_source_identity_reviewed_category_and_out_of_scope():
    with pytest.raises(ValueError, match="identity changed"):
        review.classify(raw("A1", "선블록"), approved("A1"), None)
    assert review.classify(raw("A2", "헤어메이크업류", display="쉐이딩"), None, None) == (
        None,
        "out_of_scope",
    )
    assert review.classify(
        raw("A3", "선블록", display="BB/CC"),
        {**approved("A3"), "sourceStandardCategory": "선블록"},
        None,
    ) == ("base", "reviewed_include")


def test_refuses_exclusion_that_conflicts_with_serving():
    p = product("A1")
    seed = {"products": [p], "looks": [], "stores": []}
    with pytest.raises(ValueError, match="already served"):
        review.reconcile(
            seed,
            {p["id"]: Product.model_validate(p)},
            [raw("A1", served=True)],
            {"A1": {**approved("A1"), "decision": "exclude"}},
            lambda *_: None,
            lambda _: None,
        )
