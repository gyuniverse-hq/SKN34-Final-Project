import json
from types import SimpleNamespace

import pytest

from tests.collect_g1_observations import assert_sanitized, capture
from tests.run_g1_evaluation import (
    CONTRACT,
    PREDICATES,
    content_digest,
    evaluate,
    grade,
    observation_digest,
    read_jsonl,
    verify_evidence,
)


def load_contract():
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    registry = json.loads(
        (CONTRACT / "g1_predicate_registry_PROPOSED.json").read_text(encoding="utf-8")
    )
    return cases, {entry["name"] for entry in registry["predicates"]}


def test_all_required_environments_and_both_app_entries_keep_unrun_status():
    cases, registry = load_contract()
    assert (len(cases), len(registry), len(PREDICATES)) == (47, 70, 70)
    results = list(evaluate(cases, [], registry))
    assert len(results) == 113
    cat01 = [r for r in results if r["caseId"] == "G1-CAT-01"]
    assert {(r["variantId"], r["environment"]) for r in cat01} == {
        (variant, env)
        for variant in ("category_entry", "free_chat")
        for env in ("E0", "E1", "E3", "E5")
    }
    assert {r["status"] for r in results} == {"NOT_RUN"}
    assert sum(r["humanGate"] == "NOT_RUN" for r in results) == 18


def test_observations_cannot_promote_mock_to_real_or_skip_unimplemented_predicates():
    cases, registry = load_contract()
    source = {
        "caseId": "G1-CAT-01",
        "variantId": "free_chat",
        "environment": "E1",
        "isMock": True,
        "requestId": "request-1",
        "trace": {
            "complete": True,
            "requestId": "request-1",
            "catalogHttp": [
                {"name": "catalog.search_products", "method": "GET", "path": "/api/products"}
            ],
        },
    }

    def report(item):
        return next(
            row
            for row in evaluate(cases, [item], registry)
            if row["caseId"] == item["caseId"]
            and row["variantId"] == item["variantId"]
            and row["environment"] == item["environment"]
        )

    assert report(source)["predicates"]["trace.catalog_called"] == "NOT_RUN"
    result = report(source | {"environment": "E0"})
    assert result["predicates"]["trace.catalog_called"] == "NOT_RUN"
    assert result["status"] == "NOT_RUN"


def test_empty_answer_and_unobserved_absence_are_never_passes():
    assert grade("response.schema_valid", {"response": {"answer": "  ", "products": []}}) == "FAIL"
    assert grade("trace.no_memory_write", {"trace": {"effects": []}}) == "NOT_RUN"
    assert (
        grade("response.no_fake_sale_status", {"response": {"answer": "", "products": []}})
        == "NOT_RUN"
    )
    assert grade("catalog.returned_ids_exist", {"response": {"products": []}}) == "NOT_RUN"


def test_e2_can_grade_synthetic_principals_only_on_observed_redis():
    cases, registry = load_contract()
    case = next(case for case in cases if case["caseId"] == "G1-ERR-10")
    source = {
        "caseId": case["caseId"],
        "environment": "E2",
        "isMock": False,
        "isSynthetic": True,
        "session": {"fixtureActive": True},
        "httpStatus": 403,
        "response": {"error": "Forbidden", "code": "chat_session_forbidden"},
    }

    def verdict(item):
        result = next(r for r in evaluate([case], [item], registry) if r["environment"] == "E2")
        return result["predicates"]["session.foreign_owner_denied"]

    assert verdict(source) == "NOT_RUN"
    assert verdict(source | {"realRedisConnected": True}) == "NOT_RUN"


def test_collector_binds_driver_output_and_rejects_secrets(tmp_path, monkeypatch):
    cases, registry = load_contract()
    case = next(c for c in cases if c["caseId"] == "G1-GEN-01")
    required = case["evidenceByEnvironment"]["E0"]["requiredArtifacts"]

    def run(command, *, input, **kwargs):
        request = json.loads(input)
        obs = {
            "caseId": case["caseId"],
            "caseRevision": case["caseRevision"],
            "variantId": request["variantId"],
            "environment": request["environment"],
            "runId": request["runId"],
            "response": {"answer": "예시", "products": []},
        }
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "observation": obs,
                    "artifacts": {name: {"capture": "fixture"} for name in required},
                }
            )
        )

    monkeypatch.setattr("tests.collect_g1_observations.subprocess.run", run)
    row = capture(case, "default", "E0", required, tmp_path / "driver.py", tmp_path)
    assert row["runId"] and len(row["evidenceRefs"]) == len(required)
    assert all((tmp_path / ref).is_file() for ref in row["evidenceRefs"].values())
    with pytest.raises(ValueError, match="Sensitive"):
        assert_sanitized({"sessionToken": "private"})
    assert_sanitized({"prompt_tokens": 12})


def test_cat14_review_is_bound_to_the_actual_run_and_response(tmp_path):
    cases, registry = load_contract()
    case = next(case for case in cases if case["caseId"] == "G1-CAT-14")
    binding = json.loads((CONTRACT / "g1_manifest_PROPOSED.json").read_text(encoding="utf-8"))[
        "catalogFixtureBinding"
    ]
    observation = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "environment": "E3",
        "isMock": False,
        "isSynthetic": False,
        "runId": "run-cat14",
        "llmModelId": "test-model",
        "llmModelVersion": "version-1",
        "model": {
            "isMock": False,
            "modelId": "test-model",
            "modelVersion": "version-1",
            "promptVersion": "prompt-v1",
            "responseId": "response-1",
            "requestId": "request-1",
        },
        "responseEvidenceRef": "response_snapshot.json",
        "requestId": "request-1",
        "request": {
            "method": "POST",
            "path": "/api/chat",
            "body": {"message": "틴트 추천", "requestType": "chat"},
        },
        "response": {
            "answer": "틴트는 착색이 남는 경우가 많고 립스틱은 표면에 또렷하게 발색돼요.",
            "products": [{"id": "lip-1", "brand": "fixture", "name": "립", "category": "lip"}],
        },
        "sourceSnapshotId": "catalog-snapshot",
        "sourceProductIds": ["lip-1"],
        "catalogFixtureRef": case["data"]["catalogFixtureRef"],
        "fixtureRowSha256": binding["fixtureRowSha256PostgresJsonbText"],
        "trace": {
            "complete": True,
            "requestId": "request-1",
            "catalogHttp": [
                {
                    "name": "catalog.search_products",
                    "method": "GET",
                    "path": "/api/products",
                }
            ],
        },
        "evidenceRefs": {
            name: name + ".json"
            for name in case["evidenceByEnvironment"]["E3"]["requiredArtifacts"]
        },
    }
    review = {
        "caseId": case["caseId"],
        "environmentId": "E3",
        "runId": "run-cat14",
        "modelId": "test-model",
        "modelVersion": "version-1",
        "responseEvidenceRef": "response_snapshot.json",
        "reviewer": "fixture-reviewer",
        "evaluatedAt": "2026-11-15T00:00:00Z",
        "semanticReviewStatus": "PASS",
        "coreRequirementsMet_yes_no": "YES",
        "coreGateRequired_yes_no": "YES",
        "blockingFinding_yes_no": "NO",
    }

    def write_evidence(row):
        for name, path in row["evidenceRefs"].items():
            artifact = {
                "caseId": row["caseId"],
                "caseRevision": row["caseRevision"],
                "variantId": "default",
                "environment": row["environment"],
                "runId": row["runId"],
                "observationSha256": observation_digest(row),
                "artifactType": name,
                "content": (
                    {"response": row["response"]}
                    if name == "response_snapshot"
                    else {
                        "runId": row["runId"],
                        "request": row["request"]["body"],
                        "calls": [{"responseId": "response-1", "modelId": "test-model"}],
                        "events": [
                            {
                                "event": "g1_model_completion",
                                "model_response_id": "response-1",
                                "model_id": "test-model",
                                "prompt_version": "prompt-v1",
                            }
                        ],
                    }
                    if name == "nonmock_llm_span"
                    else {
                        "runId": row["runId"],
                        "request": row["request"]["body"],
                        "actualModel": "test-model",
                        "promptVersion": "prompt-v1",
                    }
                    if name == "model_and_prompt_version"
                    else {
                        "observed": True,
                        "routeIntent": row.get("routeIntent"),
                        "catalogPreflight": row.get("catalogPreflight"),
                        "graphNodes": [{"name": "plan_turn"}] if row.get("routeIntent") else [],
                    }
                ),
            }
            artifact["contentSha256"] = content_digest(artifact["content"])
            (tmp_path / path).write_text(json.dumps(artifact), encoding="utf-8")

    write_evidence(observation)

    def report(row, reviews=()):
        return next(
            r
            for r in evaluate([case], [row], registry, reviews, evidence_root=tmp_path)
            if r["environment"] == "E3"
        )

    assert report(observation)["status"] == "NOT_RUN"
    assert report(observation, [review | {"runId": "other"}])["status"] == "NOT_RUN"
    assert report(observation, [review])["status"] == "PASS"
    span_path = tmp_path / "nonmock_llm_span.json"
    span = json.loads(span_path.read_text(encoding="utf-8"))
    span["content"]["calls"] = []
    span["contentSha256"] = content_digest(span["content"])
    span_path.write_text(json.dumps(span), encoding="utf-8")
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    span = json.loads(span_path.read_text(encoding="utf-8"))
    span["content"]["calls"][0]["responseId"] = "different-response"
    span["contentSha256"] = content_digest(span["content"])
    span_path.write_text(json.dumps(span), encoding="utf-8")
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    span = json.loads(span_path.read_text(encoding="utf-8"))
    span["content"]["runId"] = "different-run"
    span["contentSha256"] = content_digest(span["content"])
    span_path.write_text(json.dumps(span), encoding="utf-8")
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    assert report(observation | {"fixtureRowSha256": "drift"}, [review])["status"] == "BLOCKED_DATA"
    assert report(observation | {"evidenceRefs": {}}, [review])["status"] == "NOT_RUN"
    (tmp_path / "response_snapshot.json").unlink()
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    artifact = json.loads((tmp_path / "response_snapshot.json").read_text(encoding="utf-8"))
    artifact["runId"] = "different-run"
    (tmp_path / "response_snapshot.json").write_text(json.dumps(artifact), encoding="utf-8")
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    artifact = json.loads((tmp_path / "response_snapshot.json").read_text(encoding="utf-8"))
    artifact["content"]["response"]["answer"] = "변조된 응답"
    (tmp_path / "response_snapshot.json").write_text(json.dumps(artifact), encoding="utf-8")
    assert report(observation, [review])["status"] == "NOT_RUN"
    write_evidence(observation)
    assert report(observation, [review | {"semanticReviewStatus": "FAIL"}])["status"] == "FAIL"
    invalid = observation | {"response": {"answer": " ", "products": []}}
    assert report(invalid, [review])["status"] == "NOT_RUN"
    write_evidence(invalid)
    assert report(invalid, [review])["status"] == "FAIL"

    failure = observation | {"status": "FAIL", "failureReason": "actual execution failed"}
    write_evidence(failure)
    assert report(failure, [review])["status"] == "FAIL"
    span = json.loads(span_path.read_text(encoding="utf-8"))
    span["content"]["calls"] = []
    span["contentSha256"] = content_digest(span["content"])
    span_path.write_text(json.dumps(span), encoding="utf-8")
    assert report(failure, [review])["status"] == "FAIL"

    audit = observation | {
        "claimAudit": {
            "complete": True,
            "responseEvidenceRef": "response_snapshot.json",
            "claims": [
                {
                    "kind": "price",
                    "verification": "VERIFIED",
                    "evidenceRef": "tool_trace_or_no_tool_trace.json",
                }
            ],
        }
    }
    write_evidence(audit)
    key = (case["caseId"], "default", "E3")
    required = case["evidenceByEnvironment"]["E3"]["requiredArtifacts"]
    assert verify_evidence(audit, key, required, tmp_path)
    wrong_claim = audit | {
        "claimAudit": audit["claimAudit"]
        | {
            "claims": [
                {"kind": "price", "verification": "VERIFIED", "evidenceRef": "other-run.json"}
            ]
        }
    }
    write_evidence(wrong_claim)
    assert not verify_evidence(wrong_claim, key, required, tmp_path)
    self_supported = audit | {
        "claimAudit": audit["claimAudit"]
        | {
            "claims": [
                {
                    "kind": "price",
                    "verification": "VERIFIED",
                    "evidenceRef": "response_snapshot.json",
                }
            ]
        }
    }
    write_evidence(self_supported)
    assert not verify_evidence(self_supported, key, required, tmp_path)
    wrong_response = audit | {
        "claimAudit": audit["claimAudit"] | {"responseEvidenceRef": "other-run.json"}
    }
    write_evidence(wrong_response)
    assert not verify_evidence(wrong_response, key, required, tmp_path)
    linked = observation | {"routeIntent": "general", "catalogPreflight": {"runId": "run-cat14"}}
    write_evidence(linked)
    assert verify_evidence(linked, key, required, tmp_path)
    trace_path = tmp_path / "tool_trace_or_no_tool_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["content"]["routeIntent"] = "product"
    trace["contentSha256"] = content_digest(trace["content"])
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    assert not verify_evidence(linked, key, required, tmp_path)
    write_evidence(linked)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["content"]["catalogPreflight"]["runId"] = "other"
    trace["contentSha256"] = content_digest(trace["content"])
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    assert not verify_evidence(linked, key, required, tmp_path)


def test_collector_distinguishes_failure_blocking_and_missing_evidence(tmp_path, monkeypatch):
    cases, _ = load_contract()
    case = next(c for c in cases if c["caseId"] == "G1-GEN-01")
    required = case["evidenceByEnvironment"]["E0"]["requiredArtifacts"]
    result = {}

    def run(command, *, input, **kwargs):
        request = json.loads(input)
        identity = {
            "caseId": case["caseId"],
            "caseRevision": case["caseRevision"],
            "variantId": request["variantId"],
            "environment": request["environment"],
            "runId": request["runId"],
        }
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "observation": identity | result.get("observation", {}),
                    "artifacts": result.get("artifacts", {}),
                }
            )
        )

    monkeypatch.setattr("tests.collect_g1_observations.subprocess.run", run)
    result.update(observation={"status": "BLOCKED_DATA", "blockedReason": "fixture drift"})
    row = capture(case, "default", "E0", required, tmp_path / "driver.py", tmp_path)
    assert row["status"] == "BLOCKED_DATA"
    result.update(observation={"status": "NOT_RUN", "blockedReason": "case_not_implemented"})
    row = capture(case, "default", "E0", required, tmp_path / "driver.py", tmp_path)
    assert row["status"] == "NOT_RUN" and row["blockedReason"] == "case_not_implemented"
    _, registry = load_contract()
    verdict = next(r for r in evaluate([case], [row], registry) if r["environment"] == "E0")
    assert verdict["status"] == "NOT_RUN" and verdict["blockedReason"] == "case_not_implemented"
    result.update(observation={"status": "FAIL", "failureReason": "assertion failed"})
    row = capture(case, "default", "E0", required, tmp_path / "driver.py", tmp_path)
    assert row["status"] == "NOT_RUN"
    result["artifacts"] = {name: {"capture": "observed failure"} for name in required}
    row = capture(case, "default", "E0", required, tmp_path / "driver.py", tmp_path)
    assert row["status"] == "FAIL"
    assert all((tmp_path / ref).is_file() for ref in row["evidenceRefs"].values())


def test_reg07_binds_independent_requests_and_preserves_missing_baseline(tmp_path):
    cases, registry = load_contract()
    case = next(c for c in cases if c["caseId"] == "G1-REG-07")
    required = case["evidenceByEnvironment"]["E0"]["requiredArtifacts"]
    refs = {name: name + ".json" for name in required}
    evidence_ref = refs["predicate_observations"]
    normal_request = {
        "method": "POST",
        "path": "/api/chat",
        "body": {"message": "립 추천", "requestType": "chat"},
    }
    normal_response = {"answer": "추천합니다", "products": []}
    foreign_request = {
        "method": "POST",
        "path": "/api/chat",
        "body": {"message": "이전 후보", "requestType": "beauty_consultation"},
    }
    foreign_response = {"error": "Forbidden", "code": "chat_session_forbidden"}
    authorized = {
        "runId": "run-reg",
        "requestId": "normal-1",
        "request": normal_request,
        "httpStatus": 200,
        "response": normal_response,
        "evidenceRef": evidence_ref,
    }
    foreign = {
        "runId": "run-reg",
        "requestId": "foreign-1",
        "request": foreign_request,
        "httpStatus": 403,
        "response": foreign_response,
        "evidenceRef": evidence_ref,
        "responseEvidenceRef": evidence_ref,
        "session": {"fixtureActive": True},
        "trace": {"completeDomains": ["tools"], "requestId": "foreign-1", "tools": []},
        "claimAudit": {"complete": True, "responseEvidenceRef": evidence_ref, "claims": []},
    }
    auth = {"results": [200, 401], "baselineResults": [200, 401]}
    observation = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": "default",
        "environment": "E0",
        "runId": "run-reg",
        "requestId": "normal-1",
        "isMock": True,
        "httpStatus": 200,
        "request": normal_request,
        "response": normal_response,
        "auth": auth,
        "evidenceRefs": refs,
        "securityObservations": {
            "authorized": authorized,
            "foreignSession": foreign,
            "authEvidenceRef": evidence_ref,
        },
    }

    def write(row, *, captured=None):
        for name, path in refs.items():
            content = {"observed": True}
            if name == "predicate_observations":
                content = {
                    "securityObservations": captured
                    if captured is not None
                    else row.get("securityObservations"),
                    "auth": row.get("auth"),
                }
            artifact = {
                "caseId": row["caseId"],
                "caseRevision": row["caseRevision"],
                "variantId": "default",
                "environment": "E0",
                "runId": row["runId"],
                "observationSha256": observation_digest(row),
                "artifactType": name,
                "content": content,
                "contentSha256": content_digest(content),
            }
            (tmp_path / path).write_text(json.dumps(artifact), encoding="utf-8")

    def report(row):
        return next(
            x
            for x in evaluate([case], [row], registry, evidence_root=tmp_path)
            if x["environment"] == "E0"
        )

    write(observation)
    assert report(observation)["status"] == "PASS"
    no_baseline = observation | {
        "securityObservations": {"authorized": authorized, "foreignSession": foreign}
    }
    no_baseline.pop("auth")
    write(no_baseline)
    result = report(no_baseline)
    assert result["status"] == "NOT_RUN"
    assert result["predicates"] == {
        "reg.auth_unchanged": "NOT_RUN",
        "security.no_cross_user_leak": "PASS",
    }

    missing = observation | {"securityObservations": {"authorized": authorized}}
    write(missing)
    assert report(missing)["status"] == "NOT_RUN"
    wrong_top = observation | {"httpStatus": 403, "response": foreign_response}
    write(wrong_top)
    assert report(wrong_top)["status"] == "NOT_RUN"
    same = observation | {
        "securityObservations": observation["securityObservations"]
        | {"foreignSession": foreign | {"requestId": "normal-1"}}
    }
    write(same)
    assert report(same)["status"] == "NOT_RUN"
    wrong_run = observation | {
        "securityObservations": observation["securityObservations"]
        | {"foreignSession": foreign | {"runId": "different"}}
    }
    write(wrong_run)
    assert report(wrong_run)["status"] == "NOT_RUN"
    unlinked = observation | {
        "securityObservations": observation["securityObservations"]
        | {"foreignSession": foreign | {"evidenceRef": "other-run.json"}}
    }
    write(unlinked)
    assert report(unlinked)["status"] == "NOT_RUN"
    write(
        observation,
        captured={"authorized": authorized, "foreignSession": foreign | {"requestId": "different"}},
    )
    assert report(observation)["status"] == "NOT_RUN"

    exposed = foreign | {"httpStatus": 200, "response": {"answer": "private", "products": []}}
    failed = observation | {
        "securityObservations": observation["securityObservations"] | {"foreignSession": exposed}
    }
    write(failed)
    assert report(failed)["status"] == "FAIL"
    leaked = foreign | {
        "claimAudit": foreign["claimAudit"] | {"claims": [{"kind": "cross_user_data"}]}
    }
    failed = observation | {
        "securityObservations": observation["securityObservations"] | {"foreignSession": leaked}
    }
    write(failed)
    assert report(failed)["status"] == "FAIL"
    drift = observation | {"auth": {"results": [200], "baselineResults": [401]}}
    write(drift)
    assert report(drift)["status"] == "FAIL"


def test_e2_foreign_response_is_bound_to_its_existing_trace(tmp_path):
    from tests.drive_g1_e2 import session_trace_artifact

    cases, registry = load_contract()
    case = next(c for c in cases if c["caseId"] == "G1-ERR-10")
    required = case["evidenceByEnvironment"]["E2"]["requiredArtifacts"]
    refs = {name: name + ".json" for name in required}
    response = {"error": "Chat session access denied", "code": "chat_session_forbidden"}
    response_ref = refs["request_id_and_session_state_trace"]
    observation = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": "default",
        "environment": "E2",
        "runId": "run-e2",
        "requestId": "foreign-request",
        "isMock": False,
        "isSynthetic": True,
        "realRedisConnected": True,
        "httpStatus": 403,
        "response": response,
        "responseEvidenceRef": response_ref,
        "session": {"fixtureActive": True},
        "trace": {"complete": True, "requestId": "foreign-request", "tools": []},
        "claimAudit": {"complete": True, "responseEvidenceRef": response_ref, "claims": []},
        "evidenceRefs": refs,
    }
    steps = [
        {"role": "owner_preflight", "status": 200},
        {"role": "foreign_request", "status": 403, "response": response},
    ]
    trace = session_trace_artifact(
        {"runId": "run-e2"}, "foreign-request", "bootstrap", steps, observation
    )
    assert trace["response"] is observation["response"]
    assert trace["steps"][1]["response"] == trace["response"]
    assert "response" not in session_trace_artifact({}, "r", "b", [], {"caseId": "G1-REG-04"})
    for name, path in refs.items():
        content = trace if name == "request_id_and_session_state_trace" else {"observed": True}
        artifact = {
            "caseId": observation["caseId"],
            "caseRevision": observation["caseRevision"],
            "variantId": "default",
            "environment": "E2",
            "runId": "run-e2",
            "observationSha256": observation_digest(observation),
            "artifactType": name,
            "content": content,
            "contentSha256": content_digest(content),
        }
        (tmp_path / path).write_text(json.dumps(artifact), encoding="utf-8")

    def report():
        return next(
            x
            for x in evaluate([case], [observation], registry, evidence_root=tmp_path)
            if x["environment"] == "E2"
        )

    assert report()["status"] == "PASS"
    trace_path = tmp_path / response_ref
    artifact = json.loads(trace_path.read_text(encoding="utf-8"))
    artifact["content"]["requestId"] = "different-request"
    artifact["contentSha256"] = content_digest(artifact["content"])
    trace_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert report()["status"] == "NOT_RUN"
    artifact["content"]["requestId"] = observation["requestId"]
    artifact["contentSha256"] = content_digest(artifact["content"])
    trace_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert report()["status"] == "PASS"
    artifact["content"]["response"] = {"error": "other", "code": "other"}
    artifact["contentSha256"] = content_digest(artifact["content"])
    trace_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert report()["status"] == "NOT_RUN"
    del artifact["content"]["response"]
    artifact["contentSha256"] = content_digest(artifact["content"])
    trace_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert report()["status"] == "NOT_RUN"



def test_forbidden_catalog_search_is_failure_even_with_other_missing_observations(tmp_path):
    cases, registry = load_contract()
    case = next(case for case in cases if case["caseId"] == "G1-GEN-07")
    required = case["evidenceByEnvironment"]["E0"]["requiredArtifacts"]
    observation = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": "default",
        "environment": "E0",
        "runId": "forbidden-search",
        "isMock": True,
        "response": {"answer": "어떤 분위기를 원하시나요?", "products": []},
        "trace": {
            "complete": False,
            "tools": [{"name": "catalog.search_products", "callId": "call-1"}],
        },
        "evidenceRefs": {name: f"{name}.json" for name in required},
    }
    for name, path in observation["evidenceRefs"].items():
        content = {"observed": True}
        artifact = {
            "caseId": case["caseId"],
            "caseRevision": case["caseRevision"],
            "variantId": "default",
            "environment": "E0",
            "runId": observation["runId"],
            "observationSha256": observation_digest(observation),
            "artifactType": name,
            "content": content,
            "contentSha256": content_digest(content),
        }
        (tmp_path / path).write_text(json.dumps(artifact), encoding="utf-8")

    def verdict(row):
        return next(
            item for item in evaluate([case], [row], registry, evidence_root=tmp_path)
            if item["environment"] == "E0"
        )

    result = verdict(observation)
    assert result["status"] == "FAIL"
    assert result["forbiddenToolCalled"] is True

    # Missing tool observation is never treated as proof that no search happened.
    missing = observation | {"trace": {"complete": False}}
    assert verdict(missing)["status"] == "NOT_RUN"
