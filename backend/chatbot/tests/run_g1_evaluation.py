"""Grade G1 observations against the unchanged design contract."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.chat import ChatResponse

CONTRACT = Path(__file__).resolve().parents[3] / "docs/ai-alignment/04_llm_stage4_evaluation"
BLOCKED = {"BLOCKED", "BLOCKED_DATA", "BLOCKED_DEPENDENCY", "BLOCKED_FIXTURE", "BLOCKED_RIGHTS"}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def required_runs(cases):
    for case in cases:
        variants = case["input"].get("requiredVariants") or [{"variantId": "default"}]
        for variant in variants:
            for environment in case["environments"]["required"]:
                names = [
                    assertion["predicate"]
                    for assertion in case["assertions"]["automaticByEnvironment"]
                    if environment in assertion["appliesTo"]
                ]
                human = case["assertions"].get("humanGate", {})
                yield (
                    (case["caseId"], variant["variantId"], environment),
                    names,
                    human.get("mergeBlocking", False) and human.get("environment") == environment,
                    case["evidenceByEnvironment"][environment]["requiredArtifacts"],
                )


def _public_ids(observation):
    return [product["id"] for product in observation["response"]["products"]]


def _catalog_called(observation, name, path):
    return any(
        span["name"] == name and span["method"] == "GET" and span["path"] == path
        for span in observation["trace"]["catalogHttp"]
    )


def _valid_schema(observation):
    try:
        ChatResponse.model_validate(observation["response"])
    except ValidationError:
        return False
    return True


PREDICATES = {
    "catalog.category_matches": lambda o: all(
        p["category"] == o["expectedCategory"] for p in o["response"]["products"]
    ),
    "catalog.ids_match_brand": lambda o: all(
        p["brand"] == o["expectedBrand"] for p in o["response"]["products"]
    ),
    "catalog.duplicate_ids_not_exposed": lambda o: len(set(_public_ids(o))) == len(_public_ids(o)),
    "catalog.returned_ids_exist": lambda o: set(_public_ids(o)) <= set(o["sourceProductIds"]),
    "catalog.screen_id_matches": lambda o: _public_ids(o) == [o["screenProductId"]],
    "http.status_429": lambda o: o["httpStatus"] == 429,
    "response.schema_valid": _valid_schema,
    "security.no_internal_debug_fields": lambda o: (
        not ({"supervisor", "toolResult", "tool_result"} & set(o["response"]))
    ),
    "trace.catalog_called": lambda o: _catalog_called(
        o, "catalog.search_products", "/api/products"
    ),
    "trace.product_detail_called": lambda o: _catalog_called(
        o, "catalog.get_product_detail", "/api/products/{productId}"
    ),
}


def grade(name, observation):
    predicate = PREDICATES.get(name)
    if predicate is None or observation is None:
        return "NOT_RUN"
    try:
        return "PASS" if predicate(observation) else "FAIL"
    except (KeyError, TypeError):
        return "NOT_RUN"


def evaluate(cases, observations, registry):
    if not PREDICATES.keys() <= registry:
        raise ValueError("Predicate not present in the pinned registry")
    by_key = {}
    for item in observations:
        key = (item["caseId"], item.get("variantId", "default"), item["environment"])
        if key in by_key:
            raise ValueError(f"Duplicate G1 observation: {key}")
        by_key[key] = item
    for key, names, human, required_artifacts in required_runs(cases):
        observed = by_key.get(key)
        blocker = observed.get("status") if observed else None
        if blocker not in BLOCKED or not observed.get("blockedReason"):
            blocker = None
        if blocker:
            observed = None
        if observed and key[2] != "E0" and observed.get("isMock") is not False:
            observed = None
        results = {name: grade(name, observed) for name in names}
        statuses = set(results.values())
        if blocker:
            status = blocker
        elif "FAIL" in statuses:
            status = "FAIL"
        elif (
            "NOT_RUN" in statuses
            or human
            or not statuses
            or observed is None
            or not all(observed.get("evidenceRefs", {}).get(name) for name in required_artifacts)
        ):
            status = "NOT_RUN"
        else:
            status = "PASS"
        yield {
            "caseId": key[0],
            "variantId": key[1],
            "environment": key[2],
            "status": status,
            "predicates": results,
            "humanGate": "NOT_RUN" if human else None,
            "blockedReason": by_key[key]["blockedReason"] if blocker else None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    registry = json.loads(
        (CONTRACT / "g1_predicate_registry_PROPOSED.json").read_text(encoding="utf-8")
    )
    observations = read_jsonl(args.observations) if args.observations else []
    for result in evaluate(
        cases, observations, {entry["name"] for entry in registry["predicates"]}
    ):
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
