import json

from tests.run_g1_evaluation import CONTRACT, PREDICATES, evaluate, read_jsonl


def load_contract():
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    registry = json.loads(
        (CONTRACT / "g1_predicate_registry_PROPOSED.json").read_text(encoding="utf-8")
    )
    return cases, {entry["name"] for entry in registry["predicates"]}


def test_all_required_environments_and_both_app_entries_keep_unrun_status():
    cases, registry = load_contract()
    assert (len(cases), len(registry), len(PREDICATES)) == (47, 70, 10)
    results = list(evaluate(cases, [], registry))
    assert len(results) == 113
    cat01 = [r for r in results if r["caseId"] == "G1-CAT-01"]
    assert {(r["variantId"], r["environment"]) for r in cat01} == {
        (variant, env)
        for variant in ("category_entry", "free_chat")
        for env in ("E0", "E1", "E3", "E5")
    }
    assert {r["status"] for r in results} == {"NOT_RUN"}


def test_observations_cannot_promote_mock_to_real_or_skip_unimplemented_predicates():
    cases, registry = load_contract()
    source = {
        "caseId": "G1-CAT-01",
        "variantId": "free_chat",
        "environment": "E1",
        "isMock": True,
        "trace": {
            "catalogHttp": [
                {"name": "catalog.search_products", "method": "GET", "path": "/api/products"}
            ]
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
