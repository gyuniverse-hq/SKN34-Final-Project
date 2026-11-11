"""Adversarial grader verification; these are NOT chatbot performance results."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.i3_eval_adapter import (
    RECORD,
    Assertion,
    Case,
    Provenance,
    answer_invariants,
    evaluate_assertion,
    exact_equal,
    normalize_observation,
    option_invariants,
)
from tests.run_i3_eval import PACKAGE, fixture_digest, grade, load_package, main


def sample():
    case = load_package()[0]
    observation = {
        "recordType": "observation",
        "runId": "grader-test-only",
        "caseId": case.caseId,
        "turn": 1,
        "repeat": 1,
        "provenance": {
            "mode": "synthetic_contract",
            "planner": "fixture",
            "dataKind": "synthetic",
            "sutCommit": "5a112874578069dab10bd6eaebbbd50e54d71db2",
            "model": "NOT_A_MODEL_GRADER_UNIT_TEST",
            "promptHash": "a" * 64,
            "fixtureHash": case.fixtureHash,
            "dataSnapshotHash": "b" * 64,
            "dictionaryHash": "c" * 64,
            "executionRef": "unit-test-only",
            "executedAt": "2026-11-11T00:00:00Z",
            "settings": {},
        },
        "request": {
            "message": "글리세린 성분을 설명해 줘",
            "locale": "ko",
            "requestType": "beauty_consultation",
        },
        "httpStatus": 200,
        "response": {
            "answer": "발행 근거 미확인",
            "products": [],
            "claimStatus": "not_found",
            "publishedClaims": [],
        },
        "trace": {"plan": {"evidenceIntent": "explain", "explanationIngredients": ["글리세린"]}},
        "stateBefore": {"exists": False},
        "stateAfter": {"exists": False},
    }
    return case, observation


def option_response():
    return {
        "answer": "합성 옵션",
        "resultType": "recommendations",
        "products": [{"id": "a", "optionId": "a-1"}],
        "optionSearch": {
            "status": "matches",
            "exhaustive": True,
            "pages": 1,
            "evaluatedCount": 1,
            "evaluations": [
                {
                    "productId": "a",
                    "optionId": "a-1",
                    "verdict": "MATCH",
                    "budget": {
                        "verdict": "MATCH",
                        "priceBasis": "collected_sale",
                        "maxPriceKRW": 20000,
                        "reason": "within budget",
                    },
                    "ingredientConditions": [],
                    "ingredientEvidenceId": "e-1",
                    "ingredientSourceVersion": "v1",
                }
            ],
        },
        "publishedClaims": [{"publicationId": "pub-1"}],
        "optionClaimLinks": [
            {
                "publicationId": "pub-1",
                "productId": "a",
                "optionId": "a-1",
                "ingredientEvidenceId": "e-1",
                "ingredientSourceVersion": "v1",
                "finishedProductEfficacy": "unverified",
            }
        ],
    }


def test_package_has_36_candidates_47_turns_and_no_gold():
    cases = load_package()
    assert len(cases) == 36 and sum(len(c.turns) for c in cases) == 47
    assert all(c.gold.status == "candidate" and not c.gold.reviewerIds for c in cases)
    assert all(c.gold.approvedAt is None for c in cases)
    assert sum(len(t.assertions) for c in cases for t in c.turns) == 379
    reuse = json.loads((PACKAGE / "reuse_map.json").read_text(encoding="utf-8"))
    assert len(reuse["entries"]) == len({r["sourceCaseId"] for r in reuse["entries"]}) == 28


def test_schema_matches_runtime_models():
    schema = json.loads((PACKAGE / "schema.json").read_text(encoding="utf-8"))
    assert schema == RECORD.json_schema()


def test_shared_fixture_change_changes_binding():
    fixtures = json.loads((PACKAGE / "fixtures.synthetic.json").read_text(encoding="utf-8"))
    before = fixture_digest(fixtures, "Q01")
    fixtures["baseOptions"][0]["collectedSalePriceKRW"] = 1
    assert fixture_digest(fixtures, "Q01") != before


def test_all_missing_runs_remain_in_denominator():
    report = grade(load_package(), [], "real_llm", 3)
    assert report["planned"] == 141 and report["observed"] == 0
    assert report["statusCounts"] == {"BLOCKED": 141}
    assert report["scenarioStatusCounts"] == {"BLOCKED": 108}


def test_candidate_pass_does_not_approve_gold_or_claim_execution():
    case, obs = sample()
    report = grade([case], [obs], "synthetic_contract", 1)
    assert report["statusCounts"] == {"PASS": 1}
    assert report["goldApproved"] == 0 and report["goldQuality"] == "BLOCKED"
    assert report["serviceExecutedByThisCommand"] is False
    assert report["results"][0]["humanReview"] == "PENDING"


def test_normalization_preserves_raw_fields_without_oracle_enrichment():
    _, obs = sample()
    obs["response"].update(optionSearch={"status": "search_incomplete"}, publishedClaims=[])
    original = deepcopy(obs)
    normalized = normalize_observation(obs)
    assert normalized["response"] == original["response"] and obs == original
    assert "selectedProductId" not in normalized["response"]
    assert "applied" not in normalized["response"]


@pytest.mark.parametrize("mutation", ["mode", "fixture", "request", "schema", "gold"])
def test_invalid_provenance_request_schema_and_gold_are_rejected(mutation):
    case, obs = sample()
    if mutation == "mode":
        obs["provenance"]["mode"] = "real_llm"
    elif mutation == "fixture":
        obs["provenance"]["fixtureHash"] = "0" * 64
    elif mutation == "request":
        obs["request"]["message"] = "different question"
    elif mutation == "schema":
        del obs["response"]["products"]
    else:
        raw = case.model_dump()
        raw["gold"]["status"] = "approved"
        with pytest.raises(ValidationError):
            Case.model_validate(raw)
        return
    report = grade([case], [obs], "synthetic_contract", 1)
    assert report["statusCounts"] == {"FAIL": 1}


def test_fixture_planner_cannot_be_real_llm():
    _, obs = sample()
    obs["provenance"]["mode"] = "real_llm"
    with pytest.raises(ValidationError):
        Provenance.model_validate(obs["provenance"])


def test_real_llm_mode_is_separate_and_keeps_gold_blocked():
    case, obs = sample()
    obs["provenance"].update(mode="real_llm", planner="real_llm", model="test-label-only")
    assert grade([case], [obs], "synthetic_contract", 1)["statusCounts"] == {"FAIL": 1}
    report = grade([case], [obs], "real_llm", 1)
    assert report["statusCounts"] == {"PASS": 1} and report["goldQuality"] == "BLOCKED"


def test_missing_trace_is_not_filled_from_expected_plan():
    case, obs = sample()
    obs["trace"] = {}
    result = grade([case], [obs], "synthetic_contract", 1)["results"][0]
    assert result["status"] == "NOT_OBSERVABLE"
    assert result["axes"]["interpretation"] == "NOT_OBSERVABLE"


@pytest.mark.parametrize(
    "op,actual,expected,want",
    [
        ("eq", True, 1, "FAIL"),
        ("eq", {"a": True}, {"a": 1}, "FAIL"),
        ("empty", None, None, "FAIL"),
        ("empty", [], None, "PASS"),
        ("lte", True, 1, "FAIL"),
        ("lte", 20000, 20000, "PASS"),
        ("contains", [True], 1, "FAIL"),
        ("contains", ["a"], "a", "PASS"),
    ],
)
def test_strict_predicates(op, actual, expected, want):
    spec = Assertion(id="x", axis="option", path="x", op=op, expected=expected)
    assert evaluate_assertion(spec, {"x": actual})["status"] == want


def test_absence_is_not_empty_and_null_states_do_not_prove_unchanged():
    spec = Assertion(id="x", axis="conversation", path="x", op="empty", expected=None)
    assert evaluate_assertion(spec, {})["status"] == "NOT_OBSERVABLE"
    spec = spec.model_copy(update={"op": "same", "expected": "y"})
    assert evaluate_assertion(spec, {"x": None, "y": None})["status"] == "NOT_OBSERVABLE"
    spec = spec.model_copy(update={"op": "increment"})
    assert evaluate_assertion(spec, {"x": 2, "y": 1})["status"] == "PASS"
    assert evaluate_assertion(spec, {"x": 1, "y": 1})["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["option", "version", "publication", "efficacy", "evidence"])
def test_claim_join_rejects_cross_option_or_unverified_reference(mutation):
    response = option_response()
    assert all(c["status"] == "PASS" for c in option_invariants(response))
    key = {
        "option": "optionId",
        "version": "ingredientSourceVersion",
        "publication": "publicationId",
        "efficacy": "finishedProductEfficacy",
        "evidence": "ingredientEvidenceId",
    }[mutation]
    response["optionClaimLinks"][0][key] = "wrong"
    assert option_invariants(response)[-1]["status"] == "FAIL"


def test_recommendation_and_detail_have_different_card_rules():
    response = option_response()
    row = response["optionSearch"]["evaluations"][0]
    row["verdict"] = row["budget"]["verdict"] = "UNKNOWN"
    assert option_invariants(response)[0]["status"] == "FAIL"
    response["resultType"] = "product_detail"
    assert option_invariants(response)[0]["status"] == "PASS"


def test_confirmed_violation_cannot_be_downgraded_by_unknown():
    response = option_response()
    row = response["optionSearch"]["evaluations"][0]
    row["budget"]["verdict"] = "NOT_MATCH"
    row["verdict"] = "UNKNOWN"
    response["products"] = []
    assert option_invariants(response)[0]["status"] == "FAIL"


def test_missing_join_evidence_and_nonexhaustive_absence_never_pass():
    response = option_response()
    del response["publishedClaims"]
    assert option_invariants(response)[-1]["status"] == "NOT_OBSERVABLE"
    response["optionSearch"].update(status="no_matches", exhaustive=False)
    assert option_invariants(response)[0]["status"] == "FAIL"


def test_duplicate_or_unexpected_records_rejected():
    case, obs = sample()
    with pytest.raises(ValueError, match="duplicate"):
        grade([case], [obs, obs], "synthetic_contract", 1)
    obs["repeat"] = 2
    with pytest.raises(ValueError, match="Unexpected"):
        grade([case], [obs], "synthetic_contract", 1)


def test_missing_multiturn_observation_blocks_whole_scenario():
    case = next(c for c in load_package() if c.caseId == "I3-M05")
    report = grade([case], [], "synthetic_contract", 1)
    assert report["planned"] == 3 and report["scenarioStatusCounts"] == {"BLOCKED": 1}


def test_invalid_repeat_and_bool_are_not_accepted():
    for repeats in (0, -1, True):
        with pytest.raises(ValueError):
            grade([], [], "real_llm", repeats)
    assert not exact_equal([True], [1])


def test_cli_validation_and_no_observation_exit_codes(capsys):
    assert main(["--mode", "synthetic_contract", "--validate-only"]) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert main(["--mode", "real_llm"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["observed"] == 0 and report["goldApproved"] == 0


@pytest.mark.parametrize("mutation", ["request_id", "state", "run", "missing_state"])
def test_multiturn_replay_uses_actual_previous_observation(mutation):
    case, first = sample()
    second_turn = case.turns[0].model_copy(update={"turn": 2, "replayOfTurn": 1})
    case = case.model_copy(update={"turns": [case.turns[0], second_turn]})
    first["request"]["requestId"] = "00000000-0000-4000-8000-000000000001"
    first["stateAfter"] = {"exists": False, "stateVersion": 1}
    second = deepcopy(first)
    second.update(turn=2, stateBefore={"exists": False, "stateVersion": 1})
    assert grade([case], [first, second], "synthetic_contract", 1)["statusCounts"] == {"PASS": 2}
    if mutation == "request_id":
        second["request"]["requestId"] = "00000000-0000-4000-8000-000000000002"
    elif mutation == "state":
        second["stateBefore"]["stateVersion"] = 99
    elif mutation == "run":
        second["runId"] = "another-session-run"
    else:
        second["stateBefore"] = None
    report = grade([case], [first, second], "synthetic_contract", 1)
    want = "NOT_OBSERVABLE" if mutation == "missing_state" else "FAIL"
    assert report["results"][1]["status"] == want


def test_unlinked_citations_and_unspecified_card_purpose_fail():
    response = option_response()
    response["publishedClaims"].append({"publicationId": "unlinked"})
    assert option_invariants(response)[-1]["status"] == "FAIL"
    del response["resultType"]
    assert option_invariants(response)[0]["status"] == "FAIL"


@pytest.mark.parametrize("status", [409, 503])
def test_unexpected_http_error_cannot_pass_with_leftover_success_fields(status):
    case, obs = sample()
    obs["httpStatus"] = status
    obs["response"].update(error="failure", code="upstream_error")
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "FAIL"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ingredientConditions", [None]),
        ("ingredientConditions", [{}]),
        ("ingredientConditions", {"verdict": "MATCH"}),
        ("ingredientConditions", [{"verdict": "INVALID"}]),
        ("otherConditions", [None]),
        ("budget", {}),
        ("budget", []),
    ],
)
def test_malformed_option_conditions_fail_without_aborting_other_cases(field, value):
    case, obs = sample()
    malformed = deepcopy(obs)
    malformed["response"] = option_response()
    malformed["response"]["optionSearch"]["evaluations"][0][field] = value
    other = deepcopy(obs)
    other["repeat"] = 2
    report = grade([case], [malformed, other], "synthetic_contract", 2)
    assert report["results"][0]["status"] == "FAIL"
    assert report["results"][1]["status"] == "PASS"


@pytest.mark.parametrize(
    "case_id,status,code",
    [("I3-M06", 409, "chat_evidence_changed"), ("I3-M07", 503, "claim_lookup_failed")],
)
def test_expected_error_response_passes_only_for_matching_scenario(case_id, status, code):
    original = next(c for c in load_package() if c.caseId == case_id)
    turn = original.turns[-1].model_copy(update={"turn": 1, "replayOfTurn": None})
    case = original.model_copy(update={"turns": [turn]})
    _, obs = sample()
    obs.update(
        caseId=case_id,
        request=turn.request,
        httpStatus=status,
        response={"error": "failure", "code": code},
        stateBefore={"exists": True, "stateVersion": 1},
        stateAfter={"exists": True, "stateVersion": 1},
    )
    obs["provenance"]["fixtureHash"] = case.fixtureHash
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "PASS"
    del obs["stateBefore"]["exists"]
    del obs["stateAfter"]["exists"]
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "NOT_OBSERVABLE"
    obs["stateBefore"]["exists"] = obs["stateAfter"]["exists"] = True
    obs["response"]["code"] = "wrong_code"
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "FAIL"
    obs["response"]["code"] = code
    obs["httpStatus"] = 409 if status == 503 else 503
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "FAIL"


def test_valid_ingredient_and_other_conditions_and_null_budget_are_preserved():
    response = option_response()
    row = response["optionSearch"]["evaluations"][0]
    row.update(
        budget=None,
        ingredientConditions=[
            {
                "productId": "a",
                "optionId": "a-1",
                "shadeId": None,
                "condition": "ingredient",
                "ingredientName": "글리세린",
                "operator": "includes",
                "verdict": "MATCH",
                "reason": "found",
            }
        ],
        otherConditions=[{"condition": "stock", "verdict": "MATCH", "reason": "in stock"}],
    )
    assert all(c["status"] == "PASS" for c in option_invariants(response))


@pytest.mark.parametrize(
    "key,value",
    [
        ("ingredientConditions", None),
        ("ingredientConditions", [{"verdict": "MATCH"}]),
        ("otherConditions", [{"verdict": "MATCH"}]),
    ],
)
def test_incomplete_nested_condition_fails(key, value):
    case, obs = sample()
    obs["response"] = option_response()
    obs["response"]["optionSearch"]["evaluations"][0][key] = value
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "FAIL"


def test_e06_upstream_error_is_a_chat_success_with_unavailable_claims():
    case = next(c for c in load_package() if c.caseId == "I3-E06")
    _, obs = sample()
    obs.update(
        caseId=case.caseId,
        request=case.turns[0].request,
        response={
            "answer": "조회 실패",
            "products": [],
            "publishedClaims": [],
            "claimStatus": "unavailable",
        },
        trace={"plan": {"evidenceIntent": "explain"}, "claimResponses": [{"httpStatus": 503}]},
    )
    obs["provenance"]["fixtureHash"] = case.fixtureHash
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "PASS"


def test_missing_and_explicit_absent_state_are_distinct():
    case, obs = sample()
    obs["stateBefore"] = None
    result = grade([case], [obs], "synthetic_contract", 1)["results"][0]
    assert result["axes"]["conversation"] == "NOT_OBSERVABLE"
    obs["stateBefore"] = {"exists": False}
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "PASS"
    obs["stateAfter"]["exists"] = True
    assert grade([case], [obs], "synthetic_contract", 1)["results"][0]["status"] == "FAIL"


@pytest.mark.parametrize(
    "op,left,right,want",
    [
        ("different", "a", "b", "PASS"),
        ("different", "a", "a", "FAIL"),
        ("different", None, "a", "NOT_OBSERVABLE"),
        ("nonempty", "id", None, "PASS"),
        ("nonempty", " ", None, "FAIL"),
    ],
)
def test_result_set_identifier_checks(op, left, right, want):
    spec = Assertion(
        id="state",
        axis="conversation",
        path="after",
        op=op,
        expected="before" if op == "different" else None,
    )
    assert evaluate_assertion(spec, {"after": left, "before": right})["status"] == want


@pytest.mark.parametrize(
    "mutation", ["empty_answer", "status_contradiction", "bad_url", "missing_url"]
)
def test_answer_structure_and_claim_links(mutation):
    case, obs = sample()
    if mutation == "empty_answer":
        obs["response"]["answer"] = " "
    else:
        obs["response"].update(
            claimStatus="available",
            publishedClaims=[
                {"sourceUrl": "https://example.invalid/proof", "sourceTitle": "Synthetic"}
            ],
        )
        obs["response"]["answer"] = "https://example.invalid/proof"
        if mutation == "status_contradiction":
            obs["response"]["claimStatus"] = "not_found"
        elif mutation == "bad_url":
            obs["response"]["publishedClaims"][0]["sourceUrl"] = "javascript:bad"
        else:
            del obs["response"]["publishedClaims"][0]["sourceUrl"]
    result = grade([case], [obs], "synthetic_contract", 1)["results"][0]
    assert result["axes"]["answer"] == ("NOT_OBSERVABLE" if mutation == "missing_url" else "FAIL")


def test_answer_does_not_infer_semantic_truth_from_words():
    case, obs = sample()
    obs["response"]["answer"] = "안전하다고 확정할 수 없습니다."
    result = grade([case], [obs], "synthetic_contract", 1)["results"][0]
    assert result["axes"]["answer"] == "PASS"
    assert result["humanReview"] == "PENDING" and result["goldQuality"] == "BLOCKED"


def test_answer_checks_correct_citation_and_error_structure():
    response = {
        "answer": "Synthetic https://example.invalid/proof",
        "products": [],
        "claimStatus": "available",
        "publishedClaims": [
            {"sourceTitle": "Synthetic", "sourceUrl": "https://example.invalid/proof"}
        ],
    }
    assert all(
        c["status"] == "PASS"
        for c in answer_invariants({"httpStatus": 200, "response": response}, [])
    )
    response["answer"] = "Synthetic"
    assert answer_invariants({"httpStatus": 200, "response": response}, [])[-1]["status"] == "FAIL"
    checks = answer_invariants({"httpStatus": 503, "response": {"error": "", "code": "failed"}}, [])
    assert checks[0]["status"] == "FAIL"


def test_answer_axis_reports_invalid_option_claim_link():
    response = option_response()
    response["optionClaimLinks"][0]["optionId"] = "different-option"
    response.update(claimStatus="available")
    response["publishedClaims"][0].update(
        sourceTitle="Synthetic", sourceUrl="https://example.invalid"
    )
    checks = answer_invariants(
        {"httpStatus": 200, "response": response}, option_invariants(response)
    )
    assert next(c for c in checks if c["id"] == "answer_option_claim_links")["status"] == "FAIL"


@pytest.mark.parametrize(
    "coverage,want", [("full", "PASS"), ("partial", "FAIL"), (None, "NOT_OBSERVABLE")]
)
def test_absence_confirmation_requires_full_reviewed_list(coverage, want):
    response = option_response()
    row = response["optionSearch"]["evaluations"][0]
    row.update(
        ingredientCoverage=coverage,
        ingredientVerification="verified",
        ingredientConditions=[{"operator": "excludes", "verdict": "MATCH"}],
    )
    checks = answer_invariants({"httpStatus": 200, "response": response}, [])
    assert next(c for c in checks if c["id"] == "answer_absence_coverage_0")["status"] == want


def test_refinement_requires_new_result_id_and_state_continuity():
    case = next(c for c in load_package() if c.caseId == "I3-M02")
    _, first = sample()
    first.update(caseId=case.caseId, request=case.turns[0].request)
    first["provenance"]["fixtureHash"] = case.fixtureHash
    response = option_response()
    response.update(
        claimStatus="not_found",
        publishedClaims=[],
        optionClaimLinks=[],
        sessionStatus="stored",
        chatContext={"candidateIds": ["a"], "session": {"resultSetId": "result-1"}},
    )
    response["optionSearch"].update(priceBasis="collected_sale", scope="catalog")
    first.update(
        response=response,
        trace={"plan": {"evidenceIntent": "recommend"}},
        stateBefore={"exists": False},
        stateAfter={
            "exists": True,
            "stateVersion": 1,
            "resultSetId": "result-1",
            "candidateIds": ["a"],
            "ingredientConditions": ["kept"],
            "requireInStock": True,
            "maxPriceKRW": 30000,
        },
    )
    second = deepcopy(first)
    second.update(turn=2, request=case.turns[1].request, stateBefore=deepcopy(first["stateAfter"]))
    second["trace"] = {"plan": {"intent": "refine", "scope": "previous", "maxPriceKRW": 10000}}
    second["response"]["optionSearch"]["scope"] = "previous"
    second["stateAfter"].update(stateVersion=2, resultSetId="result-2", maxPriceKRW=10000)
    report = grade([case], [first, second], "synthetic_contract", 1)
    assert report["scenarioStatusCounts"] == {"PASS": 1}
    second["stateAfter"]["resultSetId"] = "result-1"
    report = grade([case], [first, second], "synthetic_contract", 1)
    assert report["results"][1]["axes"]["conversation"] == "FAIL"


def test_price_detail_preserves_result_set_identifier():
    case = next(c for c in load_package() if c.caseId == "I3-M04")
    check = next(a for a in case.turns[-1].assertions if a.id == "M04-price-result-preserved")
    assert (
        evaluate_assertion(
            check, {"stateBefore": {"resultSetId": "r1"}, "stateAfter": {"resultSetId": "r1"}}
        )["status"]
        == "PASS"
    )
    assert (
        evaluate_assertion(
            check, {"stateBefore": {"resultSetId": "r1"}, "stateAfter": {"resultSetId": "r2"}}
        )["status"]
        == "FAIL"
    )
    assert (
        evaluate_assertion(
            check, {"stateBefore": {"resultSetId": 7}, "stateAfter": {"resultSetId": 7}}
        )["status"]
        == "FAIL"
    )


def test_removed_condition_is_also_removed_from_saved_state():
    case = next(c for c in load_package() if c.caseId == "I3-M03")
    check = next(a for a in case.turns[-1].assertions if a.id == "M03-filter-state")
    kept = {"ingredientName": "글리세린", "operator": "includes"}
    removed = {"ingredientName": "향료", "operator": "excludes"}
    assert (
        evaluate_assertion(check, {"stateAfter": {"ingredientConditions": [kept]}})["status"]
        == "PASS"
    )
    assert (
        evaluate_assertion(check, {"stateAfter": {"ingredientConditions": [kept, removed]}})[
            "status"
        ]
        == "FAIL"
    )
    assert evaluate_assertion(check, {})["status"] == "NOT_OBSERVABLE"
