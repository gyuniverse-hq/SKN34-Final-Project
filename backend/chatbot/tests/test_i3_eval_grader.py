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
        "response": {"answer": "발행 근거 미확인", "products": [], "claimStatus": "not_found"},
        "trace": {"plan": {"evidenceIntent": "explain", "explanationIngredients": ["글리세린"]}},
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
                    "budget": {"verdict": "MATCH"},
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
    first["stateAfter"] = {"stateVersion": 1}
    second = deepcopy(first)
    second.update(turn=2, stateBefore={"stateVersion": 1})
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
