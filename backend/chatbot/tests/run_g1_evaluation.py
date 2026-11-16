"""Grade G1 observations against the unchanged design contract."""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from tests.g1_eval_predicates import PREDICATES, _reg07_requests

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
                    case,
                )


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def observation_digest(observation):
    """Bind evidence to the observation without creating a circular reference."""
    payload = {key: value for key, value in observation.items() if key != "evidenceRefs"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_digest(content):
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_evidence(
    observation,
    key,
    required_artifacts,
    evidence_root,
    *,
    require_e3_model=True,
    require_reg07_evidence=True,
):
    """Require local evidence JSON whose identity, artifact type and digest match the run."""
    if evidence_root is None or not evidence_root.is_dir():
        return False
    root = evidence_root.resolve(strict=True)
    refs = observation.get("evidenceRefs")
    if not isinstance(refs, dict):
        return False
    identity = {
        "caseId": key[0],
        "variantId": key[1],
        "environment": key[2],
        "caseRevision": observation.get("caseRevision"),
        "runId": observation.get("runId"),
        "observationSha256": observation_digest(observation),
    }
    contents = {}
    for artifact_type in required_artifacts:
        ref = refs.get(artifact_type)
        if not _nonblank(ref):
            return False
        try:
            path = (root / ref).resolve(strict=True)
            path.relative_to(root)
            if not path.is_file() or path.stat().st_size > 10_000_000:
                return False
            artifact = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(artifact, dict) or any(
                artifact.get(field) != value for field, value in identity.items()
            ):
                return False
            if artifact.get("artifactType") != artifact_type:
                return False
            content = artifact.get("content")
            if not isinstance(content, dict) or not content:
                return False
            contents[artifact_type] = content
            if artifact.get("contentSha256") != content_digest(content):
                return False
            if artifact_type == "response_snapshot" and content.get("response") != observation.get(
                "response"
            ):
                return False
            if (
                artifact_type == "response_snapshot"
                and observation.get("responseEvidenceRef") != ref
            ):
                return False
        except (OSError, RuntimeError, ValueError, TypeError):
            return False
    if (
        key[2] == "E2"
        and "request_id_and_session_state_trace" in contents
        and (
            not _nonblank(observation.get("requestId"))
            or contents["request_id_and_session_state_trace"].get("requestId")
            != observation["requestId"]
        )
    ):
        return False
    if (
        key[0] == "G1-REG-07"
        and require_reg07_evidence
        and not _valid_reg07_evidence(observation, contents, refs, required_artifacts)
    ):
        return False
    audit = observation.get("claimAudit")
    if audit is not None:
        if not isinstance(audit, dict):
            return False
        response_ref = audit.get("responseEvidenceRef")
        response_name = next(
            (name for name in required_artifacts if refs.get(name) == response_ref), None
        )
        if (
            not _nonblank(response_ref)
            or observation.get("responseEvidenceRef") != response_ref
            or response_name is None
            or contents[response_name].get("response") != observation.get("response")
        ):
            return False
        claims = audit.get("claims")
        if not isinstance(claims, list):
            return False
        allowed = {refs[name] for name in required_artifacts if name in refs}
        if any(
            not isinstance(claim, dict)
            or (
                claim.get("verification") == "VERIFIED"
                and (
                    claim.get("evidenceRef") not in allowed
                    or claim.get("evidenceRef") == response_ref
                )
            )
            for claim in claims
        ):
            return False
    if key[2] == "E3":
        trace = contents.get("tool_trace_or_no_tool_trace", {})
        if "catalogPreflight" in observation and (
            trace.get("catalogPreflight") != observation["catalogPreflight"]
        ):
            return False
        if "routeIntent" in observation and (
            trace.get("routeIntent") != observation["routeIntent"]
            or not isinstance(trace.get("graphNodes"), list)
            or not any(
                isinstance(node, dict) and node.get("name") == "plan_turn"
                for node in trace.get("graphNodes", [])
            )
        ):
            return False
        if require_e3_model and not _valid_e3_model(observation, contents):
            return False
    return True


def _valid_reg07_evidence(observation, contents, refs, required_artifacts):
    try:
        _reg07_requests(observation)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    security = observation.get("securityObservations")
    if not isinstance(security, dict):
        return False
    allowed = {refs[name]: name for name in required_artifacts if name in refs}
    for role in ("authorized", "foreignSession"):
        child = security.get(role)
        if not isinstance(child, dict):
            return False
        ref = child.get("evidenceRef")
        if not _nonblank(ref) or ref not in allowed:
            return False
        content = contents[allowed[ref]]
        captures = content.get("securityObservations")
        if not isinstance(captures, dict) or captures.get(role) != child:
            return False
    auth_ref = security.get("authEvidenceRef")
    if auth_ref is not None:
        if not _nonblank(auth_ref) or auth_ref not in allowed:
            return False
        if contents[allowed[auth_ref]].get("auth") != observation.get("auth"):
            return False
    return True


def _valid_e3_model(observation, contents):
    model = observation.get("model")
    span = contents.get("nonmock_llm_span", {})
    version = contents.get("model_and_prompt_version", {})
    if not isinstance(model, dict) or model.get("isMock") is not False:
        return False
    if not all(
        _nonblank(model.get(k)) for k in ("responseId", "modelId", "modelVersion", "promptVersion")
    ):
        return False
    request = observation.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("body"), dict):
        return False
    if (
        not _nonblank(observation.get("runId"))
        or span.get("runId") != observation["runId"]
        or version.get("runId") != observation["runId"]
        or span.get("request") != request["body"]
        or version.get("request") != request["body"]
        or not _nonblank(observation.get("requestId"))
        or model.get("requestId") != observation.get("requestId")
        or model["modelId"] != observation.get("llmModelId")
        or model["modelVersion"] != observation.get("llmModelVersion")
        or version.get("actualModel") != model["modelId"]
        or version.get("promptVersion") != model["promptVersion"]
    ):
        return False
    calls, events = span.get("calls"), span.get("events")
    if not isinstance(calls, list) or not isinstance(events, list):
        return False
    return any(
        isinstance(call, dict)
        and call.get("responseId") == model["responseId"]
        and call.get("modelId") == model["modelId"]
        for call in calls
    ) and any(
        isinstance(event, dict)
        and event.get("event") == "g1_model_completion"
        and event.get("model_response_id") == model["responseId"]
        and event.get("model_id") == model["modelId"]
        and event.get("prompt_version") == model["promptVersion"]
        for event in events
    )


def grade(name, observation):
    predicate = PREDICATES.get(name)
    if predicate is None or observation is None:
        return "NOT_RUN"
    try:
        result = predicate(observation)
        return "PASS" if result is True else "FAIL" if result is False else "NOT_RUN"
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return "NOT_RUN"


def _human_status(case, key, observation, reviews):
    if not observation or not all(
        _nonblank(observation.get(k))
        for k in (
            "runId",
            "responseEvidenceRef",
            "llmModelId",
            "llmModelVersion",
        )
    ):
        return "NOT_RUN"
    valid = [
        row
        for row in reviews
        if row.get("caseId") == key[0]
        and row.get("environmentId") == key[2]
        and row.get("runId") == observation["runId"]
        and row.get("responseEvidenceRef") == observation["responseEvidenceRef"]
        and row.get("modelId") == observation["llmModelId"]
        and row.get("modelVersion") == observation["llmModelVersion"]
        and all(_nonblank(row.get(k)) for k in ("reviewer", "evaluatedAt"))
    ]
    if any(
        row.get("blockingFinding_yes_no") == "YES" or row.get("semanticReviewStatus") == "FAIL"
        for row in valid
    ):
        return "FAIL"
    if any(row.get("semanticReviewStatus") == "BLOCKED" for row in valid):
        return "BLOCKED"
    passing = {
        row["reviewer"].strip()
        for row in valid
        if row.get("semanticReviewStatus") == "PASS"
        and row.get("coreRequirementsMet_yes_no") == "YES"
        and row.get("coreGateRequired_yes_no") == "YES"
        and row.get("blockingFinding_yes_no") == "NO"
        and not row.get("missingCoreRequirements")
    }
    required = case["assertions"]["humanGate"]["minimumReviewers"]
    return "PASS" if len(passing) >= required else "NOT_RUN"


def evaluate(cases, observations, registry, reviews=(), *, evidence_root=None):
    if PREDICATES.keys() != registry:
        raise ValueError("Predicates do not match the pinned registry")
    by_key = {}
    run_ids = set()
    binding = json.loads((CONTRACT / "g1_manifest_PROPOSED.json").read_text(encoding="utf-8"))[
        "catalogFixtureBinding"
    ]
    for item in observations:
        key = (item["caseId"], item.get("variantId", "default"), item["environment"])
        if key in by_key:
            raise ValueError(f"Duplicate G1 observation: {key}")
        if item.get("runId"):
            if item["runId"] in run_ids:
                raise ValueError("G1 observations cannot share a run ID")
            run_ids.add(item["runId"])
        by_key[key] = item
    for key, names, human, required_artifacts, case in required_runs(cases):
        observed = by_key.get(key)
        blocker = observed.get("status") if observed else None
        blocked_reason = None
        if observed and observed.get("status") == "NOT_RUN":
            blocked_reason = observed.get("blockedReason")
            observed = None
        if blocker not in BLOCKED or not observed.get("blockedReason"):
            blocker = None
        if blocker:
            blocked_reason = observed["blockedReason"]
            observed = None
        if (
            observed
            and key[2] != "E0"
            and (
                observed.get("isMock") is not False
                or (key[2] != "E2" and observed.get("isSynthetic") is not False)
                or (key[2] == "E2" and observed.get("realRedisConnected") is not True)
            )
        ):
            observed = None
        if observed and key[2] in {"E1", "E3", "E5"} and case["data"].get("catalogFixtureRef"):
            observed_ref = observed.get("catalogFixtureRef")
            observed_hash = observed.get("fixtureRowSha256")
            if not _nonblank(observed_ref) or not _nonblank(observed_hash):
                observed = None
            elif (
                observed_ref != case["data"]["catalogFixtureRef"]
                or observed_hash != binding["fixtureRowSha256PostgresJsonbText"]
            ):
                blocker, blocked_reason = "BLOCKED_DATA", "catalog_fixture_fingerprint_mismatch"
                observed = None
        results = {name: grade(name, observed) for name in names}
        trace = observed.get("trace") if observed else None
        tool_calls = trace.get("tools") if isinstance(trace, dict) else None
        forbidden_tools = set(case["expected"].get("forbiddenTools", []))
        forbidden_tool_called = bool(
            isinstance(tool_calls, list)
            and any(
                isinstance(call, dict) and call.get("name") in forbidden_tools
                for call in tool_calls
            )
        )
        statuses = set(results.values())
        human_status = _human_status(case, key, observed, reviews) if human else None
        refs = observed.get("evidenceRefs", {}) if observed else {}
        capture_ok = bool(
            observed
            and verify_evidence(
                observed,
                key,
                required_artifacts,
                evidence_root,
                require_e3_model=False,
                require_reg07_evidence=False,
            )
        )
        evidence_ok = bool(
            capture_ok and verify_evidence(observed, key, required_artifacts, evidence_root)
        )
        if not evidence_ok:
            results = {
                name: "NOT_RUN" if value == "PASS" else value for name, value in results.items()
            }
            statuses = set(results.values())
            if human_status == "PASS":
                human_status = "NOT_RUN"
        response = observed.get("response") if observed else None
        answer = response.get("answer") if isinstance(response, dict) else None
        invalid_answer = bool(
            observed
            and case["expected"].get("responseSchema") == "ChatResponse"
            and "response" in observed
            and (case["caseId"] != "G1-REG-07" or evidence_ok)
            and not _nonblank(answer)
        )
        if blocker:
            status = blocker
        elif capture_ok and (
            ((case["caseId"] != "G1-REG-07" or evidence_ok) and "FAIL" in statuses)
            or human_status == "FAIL"
            or forbidden_tool_called
            or invalid_answer
            or (
                capture_ok
                and observed.get("status") == "FAIL"
                and _nonblank(observed.get("failureReason"))
            )
        ):
            status = "FAIL"
        elif human_status == "BLOCKED":
            status = "BLOCKED"
        elif (
            "NOT_RUN" in statuses
            or human_status == "NOT_RUN"
            or not statuses
            or observed is None
            or not _nonblank(observed.get("runId"))
            or observed.get("caseRevision") != case["caseRevision"]
            or not all(_nonblank(refs.get(name)) for name in required_artifacts)
            or not evidence_ok
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
            "forbiddenToolCalled": forbidden_tool_called if capture_ok else None,
            "humanGate": human_status,
            "blockedReason": blocked_reason,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--human-review", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--review-template", action="store_true")
    args = parser.parse_args()
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    registry = json.loads(
        (CONTRACT / "g1_predicate_registry_PROPOSED.json").read_text(encoding="utf-8")
    )
    observations = read_jsonl(args.observations) if args.observations else []
    if args.review_template:
        fields = [
            "caseId",
            "runId",
            "modelId",
            "modelVersion",
            "evaluatedAt",
            "reviewer",
            "environmentId",
            "responseEvidenceRef",
            "coreGateRequired_yes_no",
            "coreRequirementsMet_yes_no",
            "missingCoreRequirements",
            "semanticReviewStatus",
            "semanticReviewNotes",
            "blockingFinding_yes_no",
            "blockingReason",
        ]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields)
        writer.writeheader()
        for key, _, human, required, case in required_runs(cases):
            if not human:
                continue
            matching = [
                o
                for o in observations
                if (o.get("caseId"), o.get("variantId", "default"), o.get("environment")) == key
                and o.get("caseRevision") == case["caseRevision"]
            ]
            observed = matching[0] if len(matching) == 1 else {}
            if not (
                observed
                and observed.get("isMock") is False
                and observed.get("isSynthetic") is False
                and verify_evidence(observed, key, required, args.evidence_root)
            ):
                observed = {}
            writer.writerow(
                {
                    "caseId": key[0],
                    "environmentId": key[2],
                    "coreGateRequired_yes_no": "YES",
                    "runId": observed.get("runId", ""),
                    "modelId": observed.get("llmModelId", ""),
                    "modelVersion": observed.get("llmModelVersion", ""),
                    "responseEvidenceRef": observed.get("responseEvidenceRef", ""),
                }
            )
        return
    reviews = []
    if args.human_review:
        with args.human_review.open(encoding="utf-8-sig", newline="") as handle:
            reviews = list(csv.DictReader(handle))
    for result in evaluate(
        cases,
        observations,
        {entry["name"] for entry in registry["predicates"]},
        reviews,
        evidence_root=args.evidence_root,
    ):
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
