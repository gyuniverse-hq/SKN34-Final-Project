"""Offline, stdout-only I-3 grading. No service, network, DB or model calls."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from tests.i3_eval_adapter import (
    AXES,
    Case,
    answer_invariants,
    evaluate_assertion,
    exact_equal,
    normalize_observation,
    option_invariants,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "docs/ai-alignment/04_i3_eval"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fixture_digest(fixtures, fixture_ref):
    return digest(
        {
            "shared": {k: v for k, v in fixtures.items() if k != "scenarios"},
            "scenario": fixtures["scenarios"][fixture_ref],
        }
    )


def load_package(directory=PACKAGE):
    cases = [Case.model_validate(c) for c in read_jsonl(directory / "cases.candidate.jsonl")]
    expected = {
        f"I3-{prefix}{n:02}"
        for prefix, count in (("Q", 6), ("E", 6), ("I", 6), ("O", 10), ("M", 8))
        for n in range(1, count + 1)
    }
    if len(cases) != 36 or {c.caseId for c in cases} != expected:
        raise ValueError("Exactly 36 distinct candidate scenarios required")
    fixtures = json.loads((directory / "fixtures.synthetic.json").read_text(encoding="utf-8"))
    if fixtures.get("synthetic") is not True or fixtures.get("productionEvidence") is not False:
        raise ValueError("Fixtures must explicitly deny production provenance")
    for case in cases:
        fixture = fixtures["scenarios"][case.fixtureRef]
        if fixture_digest(fixtures, case.fixtureRef) != case.fixtureHash:
            raise ValueError(f"Fixture hash mismatch: {case.caseId}")
        if len(fixture["turnSetup"]) != len(case.turns):
            raise ValueError("Every turn needs a fixture setup")
    reuse = json.loads((directory / "reuse_map.json").read_text(encoding="utf-8"))
    sources = {r["sourceCaseId"] for r in reuse["entries"]}
    if any(set(c.sourceCaseIds) - sources for c in cases):
        raise ValueError("Unknown reuse source")
    return cases


def aggregate(statuses):
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "NOT_OBSERVABLE" in statuses:
        return "NOT_OBSERVABLE"
    return "PASS" if statuses else "NOT_APPLICABLE"


def grade(cases, observations, mode, repeats):
    if mode not in {"synthetic_contract", "real_llm"} or type(repeats) is not int or repeats < 1:
        raise ValueError("Invalid mode or repeat count")
    expected_keys = {
        (c.caseId, t.turn, r) for c in cases for t in c.turns for r in range(1, repeats + 1)
    }
    indexed = {}
    for raw in observations:
        key = (raw.get("caseId"), raw.get("turn"), raw.get("repeat"))
        if key not in expected_keys or key in indexed:
            raise ValueError(f"Unexpected or duplicate observation: {key}")
        indexed[key] = raw
    results = []
    for case in cases:
        for repeat in range(1, repeats + 1):
            for turn in case.turns:
                raw = indexed.get((case.caseId, turn.turn, repeat))
                base = {
                    "caseId": case.caseId,
                    "turn": turn.turn,
                    "repeat": repeat,
                    "goldStatus": "candidate",
                    "goldQuality": "BLOCKED",
                    "humanReview": "PENDING",
                    "assertions": [],
                }
                if raw is None:
                    base.update(status="BLOCKED", reason="MISSING_EXECUTION")
                else:
                    try:
                        obs = normalize_observation(raw)
                        provenance = obs["provenance"]
                        if provenance["mode"] != mode:
                            raise ValueError("Run mode mismatch")
                        if provenance["fixtureHash"] != case.fixtureHash:
                            raise ValueError("Fixture binding mismatch")
                        for key, value in turn.request.items():
                            if key not in obs["request"] or not exact_equal(
                                obs["request"][key], value
                            ):
                                raise ValueError("Executed request differs from candidate request")
                        expected_http = [
                            a.expected
                            for a in turn.assertions
                            if a.path == "httpStatus" and a.op == "eq"
                        ]
                        if obs["httpStatus"] not in (expected_http or [200]):
                            raise ValueError("HTTP status does not match scenario")
                        checks = [evaluate_assertion(a, obs) for a in turn.assertions]
                        option_checks = option_invariants(obs["response"])
                        checks += option_checks
                        checks += answer_invariants(obs, option_checks)
                        if turn.replayOfTurn is not None:
                            prior_request = indexed.get((case.caseId, turn.replayOfTurn, repeat))
                            replay = "NOT_OBSERVABLE"
                            if prior_request and "requestId" in obs["request"]:
                                replay = (
                                    "PASS"
                                    if exact_equal(obs["request"], prior_request["request"])
                                    else "FAIL"
                                )
                            checks.append(
                                {
                                    "id": "same_retry_request",
                                    "axis": "conversation",
                                    "status": replay,
                                    "critical": True,
                                }
                            )
                        if turn.turn > 1:
                            prior = indexed.get((case.caseId, turn.turn - 1, repeat))
                            continuity = "NOT_OBSERVABLE"
                            if (
                                prior
                                and obs["stateBefore"] is not None
                                and prior.get("stateAfter") is not None
                            ):
                                same_run = obs["runId"] == prior.get("runId")
                                same_state = exact_equal(obs["stateBefore"], prior["stateAfter"])
                                continuity = "PASS" if same_run and same_state else "FAIL"
                            checks.append(
                                {
                                    "id": "turn_continuity",
                                    "axis": "conversation",
                                    "status": continuity,
                                    "critical": True,
                                }
                            )
                        base.update(
                            status=aggregate([c["status"] for c in checks]), assertions=checks
                        )
                        base["positiveContent"] = (
                            "BLOCKED_UNTIL_REAL_EVIDENCE_AND_HUMAN_GOLD"
                            if case.realEvidenceRequiredForPositiveContent
                            else "NOT_APPLICABLE"
                        )
                    except (ValueError, KeyError, TypeError) as exc:
                        base.update(status="FAIL", reason="INVALID_OBSERVATION", error=str(exc))
                base["axes"] = {
                    axis: aggregate([a["status"] for a in base["assertions"] if a["axis"] == axis])
                    if raw is not None and base.get("reason") != "INVALID_OBSERVATION"
                    else base["status"]
                    for axis in AXES
                }
                results.append(base)
    scenarios = [
        {
            "caseId": case.caseId,
            "repeat": repeat,
            "status": aggregate(
                [
                    r["status"]
                    for r in results
                    if r["caseId"] == case.caseId and r["repeat"] == repeat
                ]
            ),
        }
        for case in cases
        for repeat in range(1, repeats + 1)
    ]
    return {
        "mode": mode,
        "scope": "candidate_assertions_only",
        "goldApproved": 0,
        "goldQuality": "BLOCKED",
        "serviceExecutedByThisCommand": False,
        "executionManifest": [
            {
                "caseId": raw.get("caseId"),
                "turn": raw.get("turn"),
                "repeat": raw.get("repeat"),
                "runId": raw.get("runId"),
                "provenance": raw.get("provenance"),
            }
            for raw in observations
        ],
        "planned": len(expected_keys),
        "observed": len(indexed),
        "statusCounts": dict(Counter(r["status"] for r in results)),
        "scenarioStatusCounts": dict(Counter(s["status"] for s in scenarios)),
        "scenarios": scenarios,
        "results": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic_contract", "real_llm"), required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    cases = load_package()
    repeats = args.repeats if args.repeats is not None else (3 if args.mode == "real_llm" else 1)
    if repeats < 1:
        parser.error("repeats must be positive")
    if args.validate_only:
        print(
            json.dumps(
                {"package": "VALID", "cases": len(cases), "goldApproved": 0, "executed": False}
            )
        )
        return 0
    report = grade(
        cases, read_jsonl(args.observations) if args.observations else [], args.mode, repeats
    )
    report["packageHashes"] = {
        name: hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest()
        for name in (
            "cases.candidate.jsonl",
            "fixtures.synthetic.json",
            "schema.json",
            "reuse_map.json",
        )
    }
    print(json.dumps(report, ensure_ascii=True))
    return (
        1
        if report["statusCounts"].get("FAIL")
        else (2 if any(r["status"] != "PASS" for r in report["results"]) else 0)
    )


if __name__ == "__main__":
    raise SystemExit(main())
