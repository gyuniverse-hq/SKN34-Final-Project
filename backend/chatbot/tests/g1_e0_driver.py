"""Execute supported G1 cases through pytest with explicit synthetic dependencies."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {
    "G1-GEN-01",
    "G1-GEN-02",
    "G1-GEN-03",
    "G1-GEN-04",
    "G1-GEN-05",
    "G1-GEN-06",
    "G1-GEN-07",
    "G1-GEN-08",
    "G1-GEN-09",
    "G1-GEN-10",
    "G1-GEN-11",
    "G1-GEN-12",
    "G1-CAT-01",
    "G1-CAT-02",
    "G1-CAT-03",
    "G1-CAT-04",
    "G1-CAT-05",
    "G1-CAT-06",
    "G1-CAT-07",
    "G1-CAT-08",
    "G1-CAT-09",
    "G1-CAT-10",
    "G1-CAT-11",
    "G1-CAT-12",
    "G1-CAT-13",
    "G1-CAT-14",
    "G1-ERR-01",
    "G1-ERR-02",
    "G1-ERR-03",
    "G1-ERR-04",
    "G1-ERR-05",
    "G1-ERR-06",
    "G1-ERR-07",
    "G1-ERR-08",
    "G1-ERR-09",
    "G1-ERR-10",
    "G1-REG-01",
    "G1-REG-02",
    "G1-REG-03",
    "G1-REG-04",
    "G1-REG-05",
    "G1-REG-06",
    "G1-REG-07",
}


def run(item):
    case, variant, run_id = item["case"], item["variantId"], item["runId"]
    identity = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": variant,
        "environment": "E0",
        "runId": run_id,
    }
    if case["caseId"] not in SUPPORTED:
        return {
            "observation": identity
            | {"status": "NOT_RUN", "blockedReason": "case_not_implemented"},
            "artifacts": {},
        }
    with tempfile.TemporaryDirectory(prefix="vishue-g1-e0-") as temp:
        capture = Path(temp) / "observation.json"
        encoded = base64.b64encode(json.dumps(item, ensure_ascii=False).encode("utf-8")).decode(
            "ascii"
        )
        env = os.environ | {
            "G1_E0_CASE": encoded,
            "G1_E0_CAPTURE": str(capture),
            "PYTHONIOENCODING": "utf-8",
        }
        command = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/test_g1_e0_case_execution.py",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        if not capture.is_file():
            return {
                "observation": identity
                | {"status": "NOT_RUN", "blockedReason": "pytest_did_not_capture_case"},
                "artifacts": {},
            }
        observed = json.loads(capture.read_text(encoding="utf-8"))
    git = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    observation = identity | {
        "isMock": True,
        "isSynthetic": True,
        "requestId": run_id,
        "httpStatus": observed["httpStatus"],
        "response": observed["response"],
        "request": {
            "method": "POST",
            "path": observed.get("requestPath", "/api/chat"),
            "body": observed["request"],
        },
        "sourceSnapshotId": "e0-synthetic-catalog-fixture",
        "sourceProductIds": observed["fixtureProductIds"],
        "trace": {
            "complete": False,
            "completeDomains": ["catalogHttp"],
            "requestId": run_id,
            "catalogHttp": observed["events"],
        },
    }
    allowed = case["expected"]["allowedArgs"]
    if allowed.get("category"):
        observation["expectedCategory"] = allowed["category"]
    if case["caseId"] == "G1-CAT-03":
        observation["expectedBrand"] = allowed["q"]
    if observed.get("routeIntent") is not None:
        observation["routeIntent"] = observed["routeIntent"]
    if observed.get("securityObservations") is not None:
        observation["securityObservations"] = observed["securityObservations"]
        observation["auth"] = observed["auth"]
    if observed.get("session") is not None:
        observation["session"] = observed["session"]
    if observed.get("detailScreenProductId") is not None:
        observation["screenProductId"] = observed["detailScreenProductId"]
    if observed.get("sourceShadePairs") is not None:
        observation["sourceShadePairs"] = observed["sourceShadePairs"]
    observation.update(observed.get("shadeObservation", {}))
    if observed.get("legacyRequestId") is not None:
        observation["legacyRequestId"] = observed["legacyRequestId"]
    if observed.get("catalogPreflight") is not None:
        observation["catalogPreflight"] = observed["catalogPreflight"]
    if observed.get("catalogResultCount") is not None:
        observation["catalogResultCount"] = observed["catalogResultCount"]
    if observed.get("faultKind") is not None:
        observation["fault"] = {"kind": observed["faultKind"]}
    if observed.get("rateLimitTrace") is not None:
        observation["trace"].update(observed["rateLimitTrace"])
        observation["trace"]["completeDomains"] += ["tools", "modelCalls"]
    if observed.get("invalidPlanTrace") is not None:
        observation["trace"]["tools"] = observed["invalidPlanTrace"]["tools"]
        observation["trace"]["completeDomains"].append("tools")
    if observed.get("arSelection") is not None:
        selection = observed["arSelection"]
        observation["ar"] = {
            "selection": {"productId": selection["productId"], "shadeId": selection["shadeId"]},
            "stateVersion": observed["arStateVersion"],
        }
        if observed["response"].get("arResult", {}).get("status") != "proposed":
            observation.update(status="FAIL", failureReason="required_ar_proposal_not_produced")
    if result.returncode:
        observation.update(status="FAIL", failureReason="pytest_case_failed")
    common = {
        "runId": run_id,
        "gitCommit": git,
        "workingTreeDirty": dirty,
        "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "caseId": case["caseId"],
        "variantId": variant,
        "dependencies": "synthetic model, auth, and Catalog HTTP",
    }
    return {
        "observation": observation,
        "artifacts": {
            "test_run_log": common
            | {
                "test": "tests/test_g1_e0_case_execution.py::test_case_observation",
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            "fixture_identity": common
            | {
                "catalogProductIds": observed["fixtureProductIds"],
                "fixtureModelCalls": observed["modelCalls"],
                "fixtureBinding": observed.get("fixtureBinding"),
                "modelCallTrace": observed.get("modelCallTrace"),
                "fixtureIdentity": observed.get("fixtureIdentity"),
            },
            "predicate_observations": common
            | {
                "request": observed["request"],
                "httpStatus": observed["httpStatus"],
                "response": observed["response"],
                "catalogHttp": observed["events"],
                "routeIntent": observed.get("routeIntent"),
                "faultKind": observed.get("faultKind"),
                "catalogPreflight": observed.get("catalogPreflight"),
                "rateLimitTrace": observed.get("rateLimitTrace"),
                "invalidPlanTrace": observed.get("invalidPlanTrace"),
                "arSelection": observed.get("arSelection"),
                "arStateVersion": observed.get("arStateVersion"),
                "session": observed.get("session"),
                "foreignChecks": observed.get("foreignChecks"),
                "legacyRequestId": observed.get("legacyRequestId"),
                "detailScreenProductId": observed.get("detailScreenProductId"),
                "sourceShadePairs": observed.get("sourceShadePairs"),
                "shadeObservation": observed.get("shadeObservation"),
                "securityObservations": observed.get("securityObservations"),
                "auth": observed.get("auth"),
                "steps": observed.get("steps"),
            },
        },
    }


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    item = json.load(sys.stdin)
    try:
        print(json.dumps(run(item), ensure_ascii=False))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        case = item["case"]
        observation = {
            "caseId": case["caseId"],
            "caseRevision": case["caseRevision"],
            "variantId": item["variantId"],
            "environment": "E0",
            "runId": item["runId"],
            "status": "NOT_RUN",
            "blockedReason": type(exc).__name__,
        }
        print(json.dumps({"observation": observation, "artifacts": {}}))
