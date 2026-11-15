import json

from tests.run_g1_evaluation import CONTRACT, PREDICATES, evaluate, grade, read_jsonl


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
    assert result["predicates"]["trace.catalog_called"] == "PASS"
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
    assert verdict(source | {"realRedisConnected": True}) == "PASS"


def test_cat14_review_is_bound_to_the_actual_run_and_response():
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
        "responseEvidenceRef": "capture/response",
        "requestId": "request-1",
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
            name: "capture/" + name
            for name in case["evidenceByEnvironment"]["E3"]["requiredArtifacts"]
        },
    }
    review = {
        "caseId": case["caseId"],
        "environmentId": "E3",
        "runId": "run-cat14",
        "modelId": "test-model",
        "modelVersion": "version-1",
        "responseEvidenceRef": "capture/response",
        "reviewer": "fixture-reviewer",
        "evaluatedAt": "2026-11-15T00:00:00Z",
        "semanticReviewStatus": "PASS",
        "coreRequirementsMet_yes_no": "YES",
        "coreGateRequired_yes_no": "YES",
        "blockingFinding_yes_no": "NO",
    }

    def report(row, reviews=()):
        return next(
            r for r in evaluate([case], [row], registry, reviews) if r["environment"] == "E3"
        )

    assert report(observation)["status"] == "NOT_RUN"
    assert report(observation, [review | {"runId": "other"}])["status"] == "NOT_RUN"
    assert report(observation, [review])["status"] == "PASS"
    assert report(observation | {"fixtureRowSha256": "drift"}, [review])["status"] == "BLOCKED_DATA"
    assert report(observation | {"evidenceRefs": {}}, [review])["status"] == "NOT_RUN"
    assert report(observation, [review | {"semanticReviewStatus": "FAIL"}])["status"] == "FAIL"
    assert (
        report(observation | {"response": {"answer": " ", "products": []}}, [review])["status"]
        == "FAIL"
    )
