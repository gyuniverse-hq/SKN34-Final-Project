"""Accept an operator-recorded Expo UI run for the collector's exact run ID.

The operator captures the Expo screen, the app HTTP request/response and the server
trace separately. This driver never launches a browser or invents UI observations.
See ``request-<runId>.json`` for the case to run. Write a matching
``result-<runId>.json`` plus its PNG/JPEG screen capture into the same private folder.
The driver verifies identity, hashes, request correlation and local HEAD before binding
the supplied material to the collector. Raw screenshots remain outside the repository.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAX_IMAGE_BYTES = 5_000_000


def _identity(item):
    return {
        "caseId": item["case"]["caseId"],
        "caseRevision": item["case"]["caseRevision"],
        "variantId": item["variantId"],
        "environment": "E5",
        "runId": item["runId"],
    }


def _not_run(item, reason):
    return {
        "observation": _identity(item) | {"status": "NOT_RUN", "blockedReason": reason},
        "artifacts": {},
    }


def _read_screen(directory, screen):
    path = (directory / screen["path"]).resolve(strict=True)
    path.relative_to(directory.resolve(strict=True))
    image = path.read_bytes()
    if not 0 < len(image) <= MAX_IMAGE_BYTES:
        raise ValueError("invalid_screen_size")
    if not (image.startswith(b"\x89PNG\r\n\x1a\n") or image.startswith(b"\xff\xd8\xff")):
        raise ValueError("invalid_screen_format")
    digest = hashlib.sha256(image).hexdigest()
    if digest != screen["sha256"]:
        raise ValueError("screen_hash_mismatch")
    return {"sha256": digest, "bytesBase64": base64.b64encode(image).decode("ascii")}


def _read_trace(directory, reference):
    path = (directory / reference["path"]).resolve(strict=True)
    path.relative_to(directory.resolve(strict=True))
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError("invalid_trace_size")
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("trace_hash_mismatch")
    return json.loads(raw.decode("utf-8"))


def bind(item, capture, directory, commit):
    """Validate the operator's recorded evidence; never manufacture a missing trace."""
    identity = _identity(item)
    if any(capture.get(k) != v for k, v in identity.items()):
        raise ValueError("run_identity_mismatch")
    provenance = capture["provenance"]
    if (
        provenance["kind"] != "actual_expo_ui"
        or provenance["target"] != "expo_web"
        or provenance["commitSha"] != commit
        or not provenance["operator"]
    ):
        raise ValueError("ui_provenance_incomplete")
    captured_at = datetime.fromisoformat(provenance["capturedAt"].replace("Z", "+00:00"))
    if captured_at.tzinfo is None:
        raise ValueError("ui_capture_timezone_missing")
    client = capture["client"]
    request, response = client["request"], client["response"]
    body = request["body"]
    if request["method"] != "POST" or request["path"] != "/api/chat":
        raise ValueError("unexpected_ui_request")
    if body["message"] != item["case"]["input"]["message"]:
        raise ValueError("question_mismatch")
    variants = item["case"]["input"].get("requiredVariants", [])
    variant = next((v for v in variants if v["variantId"] == item["variantId"]), {})
    expected_type = variant.get("requestType", item["case"]["input"]["requestType"])
    if body.get("requestType", "chat") != expected_type:
        raise ValueError("request_type_mismatch")
    request_id = request["requestId"]
    server = capture["serverTrace"]
    if not request_id or server["requestId"] != request_id or not server["events"]:
        raise ValueError("server_trace_mismatch")
    recorded_client = _read_trace(directory, capture["clientTrace"])
    recorded_server = _read_trace(directory, capture["serverTraceFile"])
    if recorded_client != client or recorded_server != server:
        raise ValueError("trace_contents_mismatch")
    if not isinstance(response, dict) or not isinstance(client["httpStatus"], int):
        raise ValueError("invalid_response_capture")
    ui = capture["ui"]
    if not isinstance(ui["renderedElements"], str) or not ui["renderedElements"].strip():
        raise ValueError("ui_elements_missing")
    screen = _read_screen(directory, capture["screen"])
    observation = identity | {
        "isMock": False,
        "isSynthetic": False,
        "gitCommit": commit,
        "requestId": request_id,
        "request": request,
        "response": response,
        "httpStatus": client["httpStatus"],
        "ui": ui,
        "catalogFixtureRef": capture["fixture"]["catalogFixtureRef"],
        "fixtureRowSha256": capture["fixture"]["fixtureRowSha256"],
        "trace": server,
    }
    # Only include facts actually captured by the operator; missing facts stay NOT_RUN.
    for key in (
        "sourceProductIds",
        "sourceShadePairs",
        "sourceSnapshotId",
        "claimAudit",
        "expectedUnknownConditions",
        "routeIntent",
        "expectedCategory",
    ):
        if key in capture:
            observation[key] = capture[key]
    # Separate files and hashes establish integrity, not their capture origin. Until an
    # authenticated browser/network capture adapter is available, do not certify a
    # user-supplied bundle as an actual UI run (even when the contents appear valid).
    observation.update(status="NOT_RUN", blockedReason="ui_capture_origin_not_verified")
    common = identity | {"requestId": request_id, "provenance": provenance}
    return {
        "observation": observation,
        "artifacts": {
            "app_request_and_response_trace": common
            | {
                "request": request,
                "response": response,
                "httpStatus": client["httpStatus"],
                "serverTrace": server,
                "clientTraceSha256": capture["clientTrace"]["sha256"],
                "serverTraceSha256": capture["serverTraceFile"]["sha256"],
            },
            "UI_rendered_elements_or_screen_recording": common
            | {
                "renderedElements": ui["renderedElements"],
                "screen": screen,
            },
            "card_and_navigation_ids_if_present": common | {"ui": ui},
        },
    }


def run(item):
    configured = os.environ.get("G1_E5_CAPTURE_DIR")
    if not configured:
        return {
            "observation": _identity(item)
            | {
                "status": "BLOCKED_DEPENDENCY",
                "blockedReason": "ui_capture_directory_not_configured",
            },
            "artifacts": {},
        }
    directory = Path(configured).resolve(strict=True)
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("capture_directory_must_be_outside_repository")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        return _not_run(item, "worktree_not_clean")
    run_id = item["runId"]
    request_file = directory / f"request-{run_id}.json"
    result_file = directory / f"result-{run_id}.json"
    request_file.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    timeout = min(160, max(0, int(os.environ.get("G1_E5_CAPTURE_TIMEOUT", "150"))))
    deadline = time.monotonic() + timeout
    while not result_file.is_file():
        if time.monotonic() >= deadline:
            return _not_run(item, "operator_ui_capture_missing")
        time.sleep(0.5)
    try:
        return bind(item, json.loads(result_file.read_text(encoding="utf-8")), directory, commit)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return _not_run(item, "ui_capture_invalid_or_unmatched")


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=True))
