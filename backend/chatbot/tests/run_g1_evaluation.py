"""Grade G1 observations against the unchanged design contract."""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from tests.g1_eval_predicates import PREDICATES

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


def verify_evidence(observation, key, required_artifacts, evidence_root):
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
    return True


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
        statuses = set(results.values())
        human_status = _human_status(case, key, observed, reviews) if human else None
        refs = observed.get("evidenceRefs", {}) if observed else {}
        evidence_ok = bool(
            observed and verify_evidence(observed, key, required_artifacts, evidence_root)
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
            and not _nonblank(answer)
        )
        if blocker:
            status = blocker
        elif "FAIL" in statuses or human_status == "FAIL" or invalid_answer:
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
