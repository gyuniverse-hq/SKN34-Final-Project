"""CosIng signals must remain distinct from research evidence and option identity."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.skincare import GOALS, CosingMapping, HybridRequest, SkincareSnapshot
from app.services.skincare_service import (
    SkincareService,
    get_skincare_service,
    recommend,
    recommend_hybrid,
)
from tests.test_skincare import option, request, snapshot
from tests.test_skincare_hybrid import reviewed


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


def test_cosing_candidate_has_distinct_source_and_no_fabricated_study():
    mapping = cosing()
    data = snapshot([option(matched_mapping_ids=[mapping.mapping_id])], [mapping])
    data = SkincareSnapshot.model_validate_json(data.model_dump_json(by_alias=True))
    assert data.mappings[0].evidence_ids == []
    assert [match.option_id for match in recommend(data, request()).matches] == ["a"]
    result = recommend_hybrid(data, HybridRequest(primaryGoal="dryness"))
    assert [match.option_id for match in result.overall_top5] == ["a"]
    assert result.overall_top5[0].reasons[0].evidence_sources == ["cosing_function"]


def test_v4_uses_profile_only_for_ai_picks_and_always_returns_browse_groups():
    mappings = [cosing(mapping_id=goal, target_concern=goal) for goal in GOALS]
    options = [option(goal, matched_mapping_ids=[goal]) for goal in GOALS]
    options.append(option("shared", matched_mapping_ids=["dryness", "oiliness"]))
    repo = AsyncMock()
    repo.read.return_value = snapshot(options, mappings)
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    client = TestClient(app)
    url = "/api/recommendations/skincare/v4"
    response = client.post(
        url,
        json={
            "detectedConcerns": [{"goal": "pores", "sources": ["analysis"]}],
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["strategyVersion"] == "skincare-v4"
    assert [item["optionId"] for item in data["overallTop5"]] == ["pores"]
    assert set(data["byConcern"]) == set(GOALS)
    assert data["byConcern"]["wrinkles"][0]["reasons"][0]["sources"] == ["concern"]
    assert len(data["balanceMatches"]) == 3

    empty = client.post(url, json={}).json()
    assert empty["overallTop5"] == []
    assert empty["byConcern"]["wrinkles"] == data["byConcern"]["wrinkles"]
    assert client.post(url, json={"primaryGoal": "pores"}).status_code == 400
    assert client.post(url, json={"photo": "raw"}).status_code == 400


def test_cosing_does_not_use_another_options_ingredient_or_inactive_mapping():
    mapping = cosing()
    data = snapshot(
        [option("without", ingredient_codes=[], matched_mapping_ids=[mapping.mapping_id])],
        [mapping],
    )
    assert not recommend_hybrid(data, HybridRequest(primaryGoal="dryness")).overall_top5
    data.options[0].ingredient_codes = ["A"]
    data.mappings[0].runtime_enabled = False
    assert not recommend_hybrid(data, HybridRequest(primaryGoal="dryness")).overall_top5


def test_research_is_ignored_even_when_it_matches_the_same_option():
    original = reviewed(target_concern="pores")
    cosing_rule = cosing()
    data = snapshot(
        [option(matched_mapping_ids=[original.mapping_id, cosing_rule.mapping_id])],
        [original, cosing_rule],
    )
    result = recommend_hybrid(data, HybridRequest(primaryGoal="dryness", secondaryGoals=["pores"]))
    assert [reason.goal for reason in result.overall_top5[0].reasons] == ["dryness"]
    assert result.overall_top5[0].reasons[0].evidence_sources == ["cosing_function"]
    assert result.coverage[1].status == "mapping_unavailable"


def test_legacy_research_only_snapshot_produces_no_recommendations():
    research = reviewed()
    data = snapshot([option(matched_mapping_ids=[research.mapping_id])], [research])
    assert not recommend(data, request()).matches
    result = recommend_hybrid(data, HybridRequest(primaryGoal="dryness"))
    assert not result.overall_top5
    assert result.coverage[0].status == "mapping_unavailable"


def test_research_ingredients_cannot_change_cosing_ranking():
    cosing_rule = cosing()
    options = [
        option("a", ingredient_codes=["A"], matched_mapping_ids=[cosing_rule.mapping_id]),
        option("b", ingredient_codes=["A"], matched_mapping_ids=[cosing_rule.mapping_id]),
    ]
    clean = snapshot(options, [cosing_rule])
    mixed = clean.model_copy(deep=True)
    research = reviewed(mapping_id="research", ingredient_codes=["B"])
    mixed.mappings.append(research)
    for item in mixed.options:
        item.ingredient_codes.append("B")
        item.matched_mapping_ids.append("research")
    req = HybridRequest(primaryGoal="dryness")
    assert recommend_hybrid(mixed, req) == recommend_hybrid(clean, req)


def test_concern_and_balance_return_five_distinct_products_when_available():
    dry = cosing(mapping_id="dry", target_concern="dryness")
    options = [option(str(i), matched_mapping_ids=["dry"]) for i in range(7)]
    options.append(option("duplicate", product=options[0].product, matched_mapping_ids=["dry"]))
    result = recommend_hybrid(
        snapshot(options, [dry]), HybridRequest(primaryGoal="dryness", balanceGoal="primary")
    )
    for matches in (result.by_concern["dryness"], result.balance_matches):
        assert len(matches) == 5
        assert len({match.product.id for match in matches}) == 5
    short = recommend_hybrid(
        snapshot(options[:2], [dry]), HybridRequest(primaryGoal="dryness", balanceGoal="primary")
    )
    assert len(short.by_concern["dryness"]) == len(short.balance_matches) == 2


def test_concern_rankings_match_single_goal_requests_even_when_candidates_overlap():
    pores = cosing(mapping_id="pores", target_concern="pores")
    sensitive = cosing(mapping_id="sensitivity", target_concern="sensitivity")
    shared = [
        option(
            str(i), matched_mapping_ids=["pores", "sensitivity"], rating_avg=4.0, review_count=500
        )
        for i in range(5)
    ]
    data = snapshot(
        shared
        + [
            option("pores-only", matched_mapping_ids=["pores"], rating_avg=5.0, review_count=500),
            option(
                "sensitive-only",
                matched_mapping_ids=["sensitivity"],
                rating_avg=4.0,
                review_count=500,
                survey_ratios={"soothing": 1.0},
            ),
            option(
                "low-soothing",
                matched_mapping_ids=["sensitivity"],
                rating_avg=4.0,
                review_count=500,
                survey_ratios={"soothing": 0.0},
            ),
        ],
        [pores, sensitive],
    )
    combined = recommend_hybrid(
        data,
        HybridRequest(
            primaryGoal="pores", detectedConcerns=[{"goal": "sensitivity", "sources": ["analysis"]}]
        ),
    )
    for goal, first in (("pores", "pores-only"), ("sensitivity", "sensitive-only")):
        single = recommend_hybrid(data, HybridRequest(primaryGoal=goal))
        ids = [match.option_id for match in combined.by_concern[goal]]
        assert ids == [match.option_id for match in single.by_concern[goal]]
        assert len(ids) == 5
        assert ids[0] == first


def test_balance_prioritizes_oil_or_dryness_and_treats_conflicting_signals_equally():
    dry = cosing(mapping_id="dry", target_concern="dryness", ingredient_codes=["A"])
    oil = cosing(mapping_id="oil", target_concern="oiliness", ingredient_codes=["B"])
    data = snapshot(
        [
            option("a-dry", matched_mapping_ids=["dry"]),
            option("z-oil", ingredient_codes=["B"], matched_mapping_ids=["oil"]),
        ],
        [dry, oil],
    )
    base = {"primaryGoal": "dryness", "balanceGoal": "primary"}
    oil_signal = [{"goal": "oiliness", "sources": ["survey"]}]
    cases = [
        ({"detectedConcerns": oil_signal}, "z-oil"),
        ({"skinType": "dry"}, "a-dry"),
        ({"skinType": "dry", "detectedConcerns": oil_signal}, "a-dry"),
        ({}, "a-dry"),
    ]
    for extra, expected in cases:
        result = recommend_hybrid(data, HybridRequest(**(base | extra)))
        assert result.overall_top5[0].product.id == expected
        assert result.balance_matches[0].product.id == expected
        assert {m.product.id for m in result.balance_matches} == {"a-dry", "z-oil"}
        assert [m.product.id for m in result.by_concern["dryness"]] == ["a-dry"]
        assert [m.product.id for m in result.by_concern["oiliness"]] == ["z-oil"]
        assert {reason.sources[0] for match in result.overall_top5 for reason in match.reasons} == {
            "primary"
        }
