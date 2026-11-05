from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas.skincare import (
    IngredientMapping,
    SkincareOption,
    SkincareRequest,
    SkincareSnapshot,
)
from app.services.skincare_service import recommend
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


def request(**changes):
    return SkincareRequest(
        **(dict(primary_goal="dryness", goal_policy_version="care-goals-v1") | changes)
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(runtime_enabled=False),
        dict(identity_verified=False),
        dict(mapping_status="research_only"),
        dict(re_review_required=True),
        dict(human_mapping_review="수정필요"),
        dict(ai_paper_review="제외"),
        dict(evidence_ids=[]),
        dict(mapping_type="combination", ingredient_codes=["A", "B"]),
    ],
)
def test_unapproved_mappings_never_rank(change):
    result = recommend(snapshot(mappings=[mapping(**change)]), request())
    assert result.coverage[0].status == "mapping_unavailable"
    assert result.matches == []


@pytest.mark.parametrize("goal", ["oiliness", "blemish"])
def test_new_goals_require_approved_mappings(goal):
    req = request(primary_goal=goal)
    assert recommend(snapshot(mappings=[]), req).coverage[0].status == "mapping_unavailable"
    rejected = mapping(target_concern=goal, re_review_required=True)
    assert recommend(snapshot(mappings=[rejected]), req).coverage[0].status == "mapping_unavailable"
    approved = mapping(target_concern=goal)
    result = recommend(snapshot(mappings=[approved]), req)
    assert result.coverage[0].status == "ok"
    assert [item.product.id for item in result.matches] == ["a"]


def test_all_six_other_goals_can_be_requested():
    req = request(
        secondary_goals=["sensitivity", "pigmentation", "wrinkles", "pores", "oiliness", "blemish"]
    )
    assert len(req.secondary_goals) == 6


def test_db_option_matches_are_required_even_when_ingredients_match():
    result = recommend(snapshot(options=[option(matched_mapping_ids=[])]), request())
    assert result.coverage[0].status == "no_matches"
    assert result.matches == []
    result = recommend(snapshot(options=[option(matched_mapping_ids=["m"])]), request())
    assert [m.option_id for m in result.matches] == ["a"]


def test_db_match_never_bypasses_complete_ingredients_or_approval():
    result = recommend(
        snapshot(options=[option(matched_mapping_ids=["m"], ingredient_codes=[])]), request()
    )
    assert result.matches == []
    result = recommend(
        snapshot(
            options=[option(matched_mapping_ids=["m"])],
            mappings=[mapping(runtime_enabled=False)],
        ),
        request(),
    )
    assert result.matches == []


def test_option_price_dedup_and_stable_order():
    a = option(
        "z",
        option_id="z2",
        source_option_id="z2",
        priceKRW=500,
        skin_types=["dry"],
        label_source="manufacturer",
    )
    result = recommend(snapshot([option("z"), option("a"), a]), request(skin_type="dry"))
    assert [(m.product.id, m.option_id, m.price_krw) for m in result.matches] == [
        ("z", "z2", 500),
        ("a", "a", 100),
    ]
    reverse = recommend(snapshot([a, option("a"), option("z")]), request(skin_type="dry"))
    assert result == reverse


def test_unknown_or_unavailable_never_fills_results():
    result = recommend(
        snapshot([option(available=False), option("b", identity_verified=False)]), request()
    )
    assert result.coverage[0].status == "no_matches"
    assert not result.matches
    assert recommend(None, request()).coverage[0].status == "mapping_unavailable"


def test_priority_dominates_reviews_and_secondary_deduplicates():
    s = snapshot(
        [option("a", ingredient_codes=["B"], rating_avg=5, review_count=1000), option("z")],
        [mapping(), mapping(mapping_id="s", target_concern="pores", ingredient_codes=["B"])],
    )
    req = request(secondary_goals=["pores", "pores", "dryness"])
    assert req.secondary_goals == ["pores"]
    assert [m.product.id for m in recommend(s, req).matches] == ["z", "a"]


def test_trace_is_explicit_and_combination_is_same_option_only():
    s = snapshot(
        [option(), option("b", ingredient_codes=["B"])],
        [
            mapping(),
            mapping(mapping_id="c", mapping_type="combination", ingredient_codes=["A", "B"]),
        ],
    )
    assert recommend(s, request(include_trace=True)).trace is None
    trace = recommend(s, request(), True).trace
    assert all(not o["combinationMatches"] for o in trace["options"])


@pytest.mark.parametrize(
    "extra",
    [
        {"photo": "x"},
        {"questionnaire": {}},
        {"analysis": {}},
        {"limit": True},
        {"rating": 5},
        {"primary_goal": "unsupported"},
    ],
)
def test_invalid_private_inputs(extra):
    with pytest.raises(ValidationError):
        request(**extra)


def test_api_trace_gate(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app
    from app.services.skincare_service import get_skincare_service

    service = AsyncMock()
    service.recommend.side_effect = lambda req, trace: recommend(snapshot(), req, trace)
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: service
    monkeypatch.setattr(get_settings(), "env", "production")
    client = TestClient(app)
    response = client.post(
        "/api/recommendations/skincare",
        json=request(include_trace=True).model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert "trace" not in response.json()
    assert response.headers["cache-control"] == "no-store"
