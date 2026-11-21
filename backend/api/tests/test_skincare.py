"""Skincare snapshot fixtures and current recommendation safeguards."""

import pytest
from pydantic import ValidationError

from app.schemas.skincare import (
    CosingMapping,
    IngredientMapping,
    MappingReview,
    SkincareOption,
    SkincareProfileRequest,
    SkincareSnapshot,
)
from app.services.skincare_service import recommend_hybrid
from tests.conftest import make_product


def mapping(**changes):
    return IngredientMapping(
        **(
            dict(
                mapping_id="m",
                target_concern="dryness",
                mapping_type="single",
                ingredient_codes=["A"],
                evidence_ids=["e"],
                mapping_status="candidate_after_match",
                human_mapping_review="승인",
                ai_paper_review="승인",
                re_review_required=False,
                runtime_enabled=True,
                identity_verified=True,
            )
            | changes
        )
    )


def option(id="a", **changes):
    return SkincareOption(
        **(
            dict(
                product=make_product(id, "skincare", []),
                option_id=id,
                source_option_id=id,
                option_name=id,
                priceKRW=100,
                subcategory="cream",
                available=True,
                ingredient_codes=["A"],
                identity_verified=True,
            )
            | changes
        )
    )


def snapshot(options=None, mappings=None):
    return SkincareSnapshot(
        data_version="test",
        source_manifest={"source": "fixture"},
        mappings=mappings if mappings is not None else [mapping()],
        options=options if options is not None else [option()],
        evidence={"e": {"title": "test"}},
        ingredient_provenance={
            "A": {"source": "reviewed", "reviewedBy": "tester"},
            "B": {"source": "reviewed", "reviewedBy": "tester"},
        },
    )


def cosing(**changes):
    return CosingMapping(
        **(
            {
                "mapping_id": "cosing:42:dryness",
                "target_concern": "dryness",
                "ingredient_codes": ["A"],
                "function_names": ["HUMECTANT"],
                "substance_id": "42",
                "match_method": "exact",
            }
            | changes
        )
    )


FINGERPRINT = "a" * 64


def reviewed(**fields):
    decision = MappingReview(
        decision="approve",
        reviewer="tester",
        source="fixture review",
        fingerprint=FINGERPRINT,
        condition="none",
    )
    return mapping(
        review=decision, review_fingerprint=FINGERPRINT, evidence_verified=True, **fields
    )


def request(**changes):
    return SkincareProfileRequest(**({"skin_type": "dry"} | changes))


def test_db_option_matches_are_required_even_when_ingredients_match():
    rule = cosing()
    result = recommend_hybrid(snapshot([option(matched_mapping_ids=[])], [rule]), request())
    assert result.coverage[0].status == "no_matches"
    assert result.overall_top10 == []
    data = snapshot([option(matched_mapping_ids=[rule.mapping_id])], [rule])
    assert [m.option_id for m in recommend_hybrid(data, request()).overall_top10] == ["a"]


def test_option_price_dedup_and_stable_order():
    rule = cosing()
    a = option("a", matched_mapping_ids=[rule.mapping_id])
    z = option("z", matched_mapping_ids=[rule.mapping_id])
    preferred = option(
        "z",
        option_id="z2",
        source_option_id="z2",
        priceKRW=500,
        skin_types=["dry"],
        label_source="manufacturer",
        matched_mapping_ids=[rule.mapping_id],
    )
    result = recommend_hybrid(snapshot([z, a, preferred], [rule]), request())
    assert [(m.product.id, m.option_id, m.price_krw) for m in result.overall_top10] == [
        ("z", "z2", 500),
        ("a", "a", 100),
    ]
    assert result == recommend_hybrid(snapshot([preferred, a, z], [rule]), request())


def test_unknown_or_unavailable_never_fills_results():
    rule = cosing()
    data = snapshot(
        [
            option(available=False, matched_mapping_ids=[rule.mapping_id]),
            option("b", identity_verified=False, matched_mapping_ids=[rule.mapping_id]),
        ],
        [rule],
    )
    result = recommend_hybrid(data, request())
    assert result.coverage[0].status == "no_matches"
    assert not result.overall_top10
    assert recommend_hybrid(None, request()).coverage[0].status == "mapping_unavailable"


@pytest.mark.parametrize(
    "extra",
    [
        {"photo": "x"},
        {"questionnaire": {}},
        {"analysis": {}},
        {"limit": True},
        {"rating": 5},
        {"detectedConcerns": [{"goal": "unsupported", "sources": ["analysis"]}]},
    ],
)
def test_invalid_private_inputs(extra):
    with pytest.raises(ValidationError):
        request(**extra)
