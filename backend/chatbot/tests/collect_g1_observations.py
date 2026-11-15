"""Capture per-case driver observations and bind evidence for the G1 evaluator.

Each environment requires a separate driver. Drivers receive a JSON case request on stdin and
return a JSON object with `observation` and `artifacts`. Missing drivers are reported BLOCKED.
Artifacts must be actual run captures, with the caller responsible for sanitizing private data.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from tests.run_g1_evaluation import (
    CONTRACT,
    content_digest,
    observation_digest,
    read_jsonl,
    required_runs,
)

_SECRET_KEY = re.compile(
    r"(?i)(authorization|api.?key|password|secret|access.?token|refresh.?token|"
    r"session.?token|database.?url|email|face.?image|face.?video)"
)
_SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+\S+|sk-[a-z0-9_-]{16,}|postgres(?:ql)?://\S+|"
    r"eyJ[a-z0-9_-]+\.eyJ[a-z0-9_-]+\.[a-z0-9_-]+)"
)


def assert_sanitized(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(key) and item not in (None, "", "[REDACTED]"):
                raise ValueError("Sensitive field in evidence")
            assert_sanitized(item)
    elif isinstance(value, list):
        for item in value:
            assert_sanitized(item)
    elif isinstance(value, str) and _SECRET_TEXT.search(value):
        raise ValueError("Sensitive value in evidence")


def capture(case, variant, environment, required, executable, evidence_root):
    run_id = uuid4().hex
    request = {"case": case, "variantId": variant, "environment": environment, "runId": run_id}
    identity = {
        "caseId": case["caseId"], "caseRevision": case["caseRevision"], "variantId": variant,
        "environment": environment, "runId": run_id,
    }
    try:
        command = (
            [sys.executable, "-B", str(executable)]
            if executable.suffix == ".py"
            else [str(executable)]
        )
        result = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=180,
            check=True,
        )
        data = json.loads(result.stdout)
        observation = data["observation"]
        artifacts = data["artifacts"]
        assert_sanitized(data)
        expected = identity
        if any(observation.get(field) != value for field, value in expected.items()):
            raise ValueError("Driver observation does not match run")
        if observation.get("status") in {
            "BLOCKED_DEPENDENCY", "BLOCKED_DATA", "BLOCKED_FIXTURE", "BLOCKED_RIGHTS", "BLOCKED"
        }:
            if (
                not isinstance(observation.get("blockedReason"), str)
                or not observation["blockedReason"].strip()
            ):
                raise ValueError("Missing blocked reason")
            return observation
        if observation.get("status") == "FAIL" and not observation.get("failureReason"):
            raise ValueError("Missing failure reason")
        if set(artifacts) != set(required):
            raise ValueError("Driver did not capture the required artifacts")
        if any(not isinstance(content, dict) or not content for content in artifacts.values()):
            raise ValueError("Evidence artifact is empty")
        if "response_snapshot" in artifacts and (
            artifacts["response_snapshot"].get("response") != observation.get("response")
        ):
            raise ValueError("Response artifact does not match observation")
        if "response_snapshot" in artifacts:
            observation["responseEvidenceRef"] = f"{run_id}/response_snapshot.json"
        observation["evidenceRefs"] = {name: f"{run_id}/{name}.json" for name in required}
        digest = observation_digest(observation)
        directory = evidence_root / run_id
        directory.mkdir(mode=0o700)
        for name, content in artifacts.items():
            envelope = expected | {
                "observationSha256": digest,
                "contentSha256": content_digest(content),
                "artifactType": name,
                "content": content,
            }
            (directory / f"{name}.json").write_text(
                json.dumps(envelope, ensure_ascii=False), encoding="utf-8"
            )
        return observation
    except (OSError, subprocess.SubprocessError):
        return identity | {"status": "BLOCKED_DEPENDENCY", "blockedReason": "driver_unavailable"}
    except (ValueError, TypeError, KeyError):
        return identity | {"status": "NOT_RUN", "blockedReason": "invalid_or_missing_evidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("E0", "E1", "E2", "E3", "E5"), required=True)
    parser.add_argument("--driver", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    repository = CONTRACT.parents[2].resolve()
    if root == repository or repository in root.parents:
        parser.error("Evidence directory must be outside the repository")
    root.mkdir(parents=True, exist_ok=True)
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    for key, _, _, required, case in required_runs(cases):
        if key[2] != args.environment or (args.case_id and key[0] not in args.case_id):
            continue
        if args.driver is None:
            item = {
                "caseId": key[0],
                "caseRevision": case["caseRevision"],
                "variantId": key[1],
                "environment": key[2],
                "status": "BLOCKED_DEPENDENCY",
                "blockedReason": "environment_driver_not_configured",
            }
        else:
            item = capture(case, key[1], key[2], required, args.driver.resolve(strict=True), root)
        print(json.dumps(item, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.exit(main())
