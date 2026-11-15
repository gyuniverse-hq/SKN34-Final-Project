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
    "G1-GEN-02",
    "G1-GEN-04",
    "G1-GEN-05",
    "G1-GEN-06",
    "G1-GEN-10",
    "G1-CAT-01",
    "G1-CAT-03",
    "G1-CAT-09",
    "G1-CAT-14",
    "G1-REG-01",
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
        "request": {"method": "POST", "path": "/api/chat", "body": observed["request"]},
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
            },
            "predicate_observations": common
            | {
                "request": observed["request"],
                "httpStatus": observed["httpStatus"],
                "response": observed["response"],
                "catalogHttp": observed["events"],
                "routeIntent": observed.get("routeIntent"),
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
