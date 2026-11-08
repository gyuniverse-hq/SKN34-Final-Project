# Historical research fixtures exercise the ranking core independently of the CosIng policy.

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.skincare import CosingMapping, HybridRequest, MappingReview
from app.services.skincare_service import (
    SkincareService,
    get_skincare_service,
)
from app.services.skincare_service import (
    _recommend_hybrid_unfiltered as recommend_hybrid,
)
from app.services.skincare_service import (
    _recommend_unfiltered as recommend,
)
from app.services.skincare_service import (
    _review_preview_unfiltered as review_preview,
)
from tests.test_skincare import mapping, option, request, snapshot

FINGERPRINT = "a" * 64


def distinct_ingredients(data):
    """Use distinct ingredient/evidence bases for tests of complementary care."""
    for m in data.mappings:
        m.ingredient_codes = [m.mapping_id]
        m.evidence_ids = [m.mapping_id]
        data.ingredient_provenance[m.mapping_id] = {"source": "fixture", "reviewedBy": "tester"}
        data.evidence[m.mapping_id] = {"title": "fixture"}
    for o in data.options:
        o.ingredient_codes = list(o.matched_mapping_ids)
    return type(data).model_validate(data.model_dump())


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


def test_goal_precedence_and_independent_group_representatives():
    dry = reviewed()
    pore = reviewed(mapping_id="p", target_concern="pores", ingredient_codes=["B"])
    options = [option(str(i), matched_mapping_ids=["m"]) for i in range(6)]
    other_option = option(
        "alternate", product=options[0].product, ingredient_codes=["B"], matched_mapping_ids=["p"]
    )
    options += [other_option, option("outside", ingredient_codes=["B"], matched_mapping_ids=["p"])]
    data = snapshot(options, [dry, pore])
    req = HybridRequest(
        primaryGoal="dryness", detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}]
    )
    first = recommend_hybrid(data, req)
    assert len(first.overall_top5) == 5
    assert len({m.product.id for m in first.overall_top5}) == 5
    assert first.overall_top5[0].option_id == "alternate"
    assert [m.option_id for m in first.by_concern["pores"]] == ["alternate", "outside"]
    assert [m.option_id for m in first.by_concern["dryness"]] == list("01234")
    assert first.by_concern["pores"][0].reasons[0].sources == ["analysis"]
    data.options.reverse()
    assert recommend_hybrid(data, req) == first
    changed = recommend_hybrid(
        data,
        HybridRequest(
            primaryGoal="pores",
            secondaryGoals=["dryness"],
            detectedConcerns=req.detected_concerns,
        ),
    )
    assert changed.overall_top5[0].option_id == "alternate"
    assert set(changed.by_concern) == set(first.by_concern)
    assert changed.by_concern["dryness"][-1].option_id == "4"


@pytest.mark.parametrize("count", range(5))
def test_manual_goal_only_and_short_lists(count):
    data = snapshot([option(str(i), matched_mapping_ids=["m"]) for i in range(count)], [reviewed()])
    result = recommend_hybrid(data, HybridRequest(primaryGoal="dryness"))
    assert len(result.overall_top5) == count
    assert len(result.by_concern["dryness"]) == min(count, 5)
    assert result.coverage[0].status == ("ok" if count else "no_matches")


def test_current_review_and_same_option_proof_required_even_for_imported_snapshots():
    m = reviewed()
    m.review.condition = "option_proof"
    m.review.requirement = "verified concentration"
    m.review.option_proofs = {"verified": "product specification"}
    data = snapshot(
        [
            option("unverified", matched_mapping_ids=["m"]),
            option("verified", ingredient_codes=["B"], matched_mapping_ids=["m"]),
            option("legacy", matched_mapping_ids=None),
        ],
        [m],
    )
    req = HybridRequest(primaryGoal="dryness")
    assert recommend_hybrid(data, req).coverage[0].status == "no_matches"
    assert review_preview(data)["coverage"]["dryness"] == {
        "activeMappings": 1,
        "matchedOptions": 1,
        "eligibleProducts": 0,
    }
    data.options[1].ingredient_codes = ["A"]
    assert [x.option_id for x in recommend_hybrid(data, req).overall_top5] == ["verified"]
    for decision in ["revoke", "re_review"]:
        m.review.decision = decision
        assert recommend_hybrid(data, req).coverage[0].status == "mapping_unavailable"
    m.review.decision = "approve"
    m.review_fingerprint = "b" * 64
    assert "review_source_changed" in review_preview(data)["mappings"]["m"]["blocked"]
    assert not recommend_hybrid(data, req).overall_top5
    assert not recommend_hybrid(snapshot(), req).overall_top5


def test_unsupported_catalog_goal_stays_visible_only_in_the_review_preview():
    data = snapshot(mappings=[reviewed(target_concern="future_goal")])
    assert review_preview(data)["mappings"]["m"]["blocked"] == ["unsupported_goal"]
    assert not recommend_hybrid(data, HybridRequest(primaryGoal="dryness")).overall_top5


def test_sources_deduplicated_and_user_goal_not_scored_twice():
    goals = [reviewed(), reviewed(mapping_id="p", target_concern="pores", ingredient_codes=["B"])]
    data = snapshot(
        [
            option("a", matched_mapping_ids=["m"]),
            option("z", ingredient_codes=["A", "B"], matched_mapping_ids=["m", "p"]),
        ],
        goals,
    )
    req = HybridRequest(
        primaryGoal="dryness",
        secondaryGoals=["dryness"],
        detectedConcerns=[
            {"goal": "dryness", "sources": ["survey", "survey"]},
            {"goal": "pores", "sources": ["analysis"]},
        ],
    )
    first = recommend_hybrid(data, req).overall_top5[0]
    assert first.option_id == "z"
    assert first.reasons[0].sources == ["primary", "survey"]


def test_fastapi_v2_wire_contract_and_private_input_rejection():
    repo = AsyncMock()
    cosing = CosingMapping(mapping_id="m", target_concern="dryness", ingredient_codes=["A"],
                           function_names=["HUMECTANT"], substance_id="42", match_method="exact")
    repo.read.return_value = snapshot([option(matched_mapping_ids=["m"])], [cosing])
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    client = TestClient(app)
    url = "/api/recommendations/skincare/v2"
    response = client.post(url, json={"primaryGoal": "dryness"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"overallTop5", "byConcern", "coverage", "strategyVersion", "dataVersion"}
    assert body["overallTop5"][0]["priceKRW"] == 100
    assert body["overallTop5"] == body["byConcern"]["dryness"]
    invalid = client.post(url, json={"primaryGoal": "dryness", "photo": "raw"})
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_request"


def test_chosen_goal_and_detected_care_both_enter_the_overall_pool():
    # Synthetic comparison: same candidates and approval data in both strategies.
    mappings = [
        reviewed(mapping_id=goal, target_concern=goal)
        for goal in ("dryness", "pores", "wrinkles", "pigmentation")
    ]
    data = snapshot(
        [
            option("chosen", matched_mapping_ids=["dryness", "pores"]),
            option("detected", matched_mapping_ids=["dryness", "wrinkles", "pigmentation"]),
        ],
        mappings,
    )
    old = recommend(data, request(secondary_goals=["pores", "wrinkles", "pigmentation"]))
    new = recommend_hybrid(
        data,
        HybridRequest(
            primaryGoal="dryness",
            secondaryGoals=["pores"],
            detectedConcerns=[
                {"goal": goal, "sources": ["analysis"]} for goal in ("wrinkles", "pigmentation")
            ],
        ),
    )
    assert [m.product.id for m in old.matches] == ["detected", "chosen"]
    assert {m.product.id for m in new.overall_top5} == {"detected", "chosen"}
    assert [m.product.id for m in new.by_concern["pores"]] == ["chosen"]


def test_overall_balances_care_across_five_products_and_groups_stay_independent():
    goals = ("dryness", "pores", "wrinkles")
    mappings = [reviewed(mapping_id=g, target_concern=g) for g in goals]
    data = snapshot(
        [option(f"dry-{i}", matched_mapping_ids=["dryness"]) for i in range(7)]
        + [option(f"pore-{i}", matched_mapping_ids=["pores"]) for i in range(3)]
        + [option(f"wrinkle-{i}", matched_mapping_ids=["wrinkles"]) for i in range(3)],
        mappings,
    )
    data = distinct_ingredients(data)
    req = HybridRequest(
        primaryGoal="dryness",
        detectedConcerns=[{"goal": g, "sources": ["analysis"]} for g in goals],
    )
    result = recommend_hybrid(data, req)
    assert len(result.overall_top5) == 5
    assert {r.goal for m in result.overall_top5 for r in m.reasons} == set(goals)
    for goal in goals:
        assert all(goal in {r.goal for r in m.reasons} for m in result.by_concern[goal])
    assert result.by_concern["dryness"][-1].product.id == "dry-4"
    assert "dry-2" not in {m.product.id for m in result.overall_top5}
    data.options.reverse()
    assert recommend_hybrid(data, req) == result


def test_multi_concern_option_complements_coverage_without_mixing_product_options():
    goals = ("dryness", "pores", "wrinkles")
    mappings = [reviewed(mapping_id=g, target_concern=g) for g in goals]
    dry = option("a-dry", matched_mapping_ids=["dryness"])
    other = option("a-other", product=dry.product, matched_mapping_ids=["pores", "wrinkles"])
    data = snapshot([dry, other, option("b", matched_mapping_ids=["dryness"])], mappings)
    data = distinct_ingredients(data)
    result = recommend_hybrid(
        data,
        HybridRequest(
            primaryGoal="dryness",
            detectedConcerns=[{"goal": g, "sources": ["analysis"]} for g in goals],
        ),
    )
    assert [m.option_id for m in result.overall_top5] == ["a-other", "b"]
    assert {r.goal for r in result.overall_top5[0].reasons} == {"pores", "wrinkles"}
    assert result.by_concern["dryness"][0].option_id == "a-dry"


@pytest.mark.parametrize("count", range(5))
def test_short_lists_include_both_chosen_and_detected_products(count):
    data = snapshot(
        [option(f"p{i}", matched_mapping_ids=["p"]) for i in range(count)]
        + [option("manual-only", matched_mapping_ids=["m"])],
        [reviewed(), reviewed(mapping_id="p", target_concern="pores")],
    )
    result = recommend_hybrid(
        data,
        HybridRequest(
            primaryGoal="dryness", detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}]
        ),
    )
    assert len(result.overall_top5) == count + 1
    assert any(m.product.id == "manual-only" for m in result.overall_top5)
    assert result.by_concern["dryness"][0].product.id == "manual-only"


def test_missing_care_mapping_keeps_other_eligible_perspectives_and_explains_the_gap():
    data = snapshot([option(matched_mapping_ids=["m"])], [reviewed()])
    req = HybridRequest(
        primaryGoal="dryness", detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}]
    )
    result = recommend_hybrid(data, req)
    assert len(result.overall_top5) == 1
    assert {c.goal: c.status for c in result.coverage} == {
        "dryness": "ok",
        "pores": "mapping_unavailable",
    }


def test_goal_analysis_and_skin_mix_without_a_fixed_quota_or_forcing_low_ratings(monkeypatch):
    goals = ("pigmentation", "pores", "dryness")
    mappings = [reviewed(mapping_id=g, target_concern=g) for g in goals]
    options = [
        option(f"{g}-{i}", matched_mapping_ids=[g], rating_avg=4.8, review_count=1000)
        for g in goals
        for i in range(6)
    ]
    data = snapshot(options, mappings)
    data = distinct_ingredients(data)
    options = data.options
    req = HybridRequest(
        primaryGoal="pigmentation",
        skinType="dry",
        detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}],
    )
    result = recommend_hybrid(data, req)
    assert len(result.overall_top5) == 5
    assert {r.goal for m in result.overall_top5 for r in m.reasons} == set(goals)
    skin = result.by_concern["dryness"][0]
    assert skin.reasons[0].sources == ["skinProfile"]
    monkeypatch.setattr("app.services.skincare_service.COMPLEMENT_WEIGHT", 0)
    monkeypatch.setattr("app.services.skincare_service.REDUNDANCY_WEIGHT", 0)
    without_complement = recommend_hybrid(data, req)
    assert all(m.reasons[0].goal == "pigmentation" for m in without_complement.overall_top5)
    monkeypatch.setattr("app.services.skincare_service.COMPLEMENT_WEIGHT", 1)
    monkeypatch.setattr("app.services.skincare_service.REDUNDANCY_WEIGHT", 0.5)
    for o in options:
        if o.matched_mapping_ids == ["pigmentation"]:
            o.rating_avg = 4.83
    preferred = recommend_hybrid(data, req)
    assert sum(m.reasons[0].goal == "pigmentation" for m in preferred.overall_top5) == 3
    assert {r.goal for m in preferred.overall_top5 for r in m.reasons} == set(goals)
    # A missing perspective does not reserve seats; strong goal products can take all five.
    for o in options:
        if o.matched_mapping_ids != ["pigmentation"]:
            o.rating_avg = 1.0
    weaker = recommend_hybrid(data, req)
    assert all(m.reasons[0].goal == "pigmentation" for m in weaker.overall_top5)
    # Repeated evidence for the same care need does not multiply its gain.
    duplicate = req.model_copy(deep=True)
    duplicate.detected_concerns += duplicate.detected_concerns
    assert recommend_hybrid(data, duplicate) == weaker


def test_skin_only_candidates_require_active_same_option_mapping():
    req = HybridRequest(primaryGoal="pigmentation", skinType="dry", irritationSignal="caution")
    data = snapshot([option(matched_mapping_ids=["m"])], [reviewed()])
    result = recommend_hybrid(data, req)
    assert result.overall_top5[0].reasons[0].sources == ["skinProfile"]
    data.mappings[0].runtime_enabled = False
    assert recommend_hybrid(data, req).overall_top5 == []
    data.mappings[0].runtime_enabled = True
    data.options[0].ingredient_codes = ["B"]
    assert recommend_hybrid(data, req).overall_top5 == []


def test_same_need_across_goal_detection_and_skin_does_not_receive_multiple_bonuses():
    data = snapshot(
        [option(str(i), matched_mapping_ids=[g]) for i, g in enumerate(["m", "p"] * 4)],
        [reviewed(), reviewed(mapping_id="p", target_concern="pores")],
    )
    req = HybridRequest(
        primaryGoal="dryness", detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}]
    )
    first = recommend_hybrid(data, req)
    req.skin_type = "dry"
    req.detected_concerns.append(
        req.detected_concerns[0].model_copy(update={"goal": "dryness", "sources": ["skinType"]})
    )
    second = recommend_hybrid(data, req)
    assert [m.option_id for m in first.overall_top5] == [m.option_id for m in second.overall_top5]
