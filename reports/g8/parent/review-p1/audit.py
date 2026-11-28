"""Bounded lifecycle regression evidence; export summaries, never raw service payloads."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BASE = "e97272dd859ddff329907b539ec7c2884a753d92"
PRODUCTS = [
    "backend/chatbot/app/services/consultation_parent_graph.py",
    "backend/chatbot/app/services/consultation_intent_service.py",
    "backend/chatbot/app/services/consultation_result_service.py",
]
TESTS = [
    "backend/chatbot/tests/test_g8_consultation_parent.py",
    "backend/chatbot/tests/test_g8_consultation_intent.py",
    "backend/chatbot/tests/test_g7_conversation_api_pg.py",
]
DOCS = ["docs/ai-design/G8-IMPLEMENTATION-SPEC.md", "docs/ai-design/G8-WORKLOG.md"]
ARTIFACTS = ["audit.py", "lifecycle-verification.json", "checks.log", "security.log"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def read():
    return json.loads((OUT / "lifecycle-verification.json").read_text(encoding="utf-8"))


def write(data):
    (OUT / "lifecycle-verification.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def baseline():
    assert git("rev-parse", "HEAD").decode().strip() == BASE
    assert not git("diff", "--name-only").strip()
    assert not (OUT / "lifecycle-verification.json").exists()
    names = git("ls-files", "-z").decode().split("\0")
    sources, evidence = [], []
    for name in filter(None, names):
        p = ROOT / name
        if name.startswith("reports/g8/"):
            evidence.append({"path": name, "sha256": sha(p.read_bytes())})
        elif p.suffix in {".py", ".ts", ".tsx"} and not name.startswith("reports/"):
            sources.append({"path": name, "sha256": sha(p.read_bytes())})
    write(
        {
            "at": datetime.now(UTC).isoformat(),
            "baseHead": BASE,
            "approvedProducts": PRODUCTS,
            "approvedTests": TESTS,
            "approvedDocuments": DOCS,
            "approvedArtifacts": ARTIFACTS,
            "sourceBaseline": sources,
            "priorEvidenceBaseline": evidence,
            "runs": [],
            "newPaidModelCalls": 0,
            "dataSharingP1": "OPEN; outside this two-lifecycle-defect fix; no old evidence edited",
            "PR": {
                "number": 309,
                "draft": True,
                "remoteCI": "existing BASE passed; new source NOT_RUN",
            },
            "commitPushMergeDeploy": "NOT_RUN",
        }
    )
    print(f"Baseline: {len(sources)} sources, {len(evidence)} old evidence files")


def run(command, cwd, *, phase, env=None, expect_failure=False):
    started = datetime.now(UTC)
    sources = [{"path": p, "sha256": sha((ROOT / p).read_bytes())} for p in PRODUCTS + TESTS]
    result = subprocess.run(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # Failed assertions can include source excerpts. Keep original stdout outside Git.
    private = Path(tempfile.gettempdir()) / "vishue-g8-review-p1-private"
    private.mkdir(exist_ok=True)
    raw = private / (uuid.uuid4().hex + ".log")
    raw.write_bytes(result.stdout)
    text = result.stdout.decode("utf-8", errors="replace")
    counts = [
        (int(n), kind)
        for n, kind in re.findall(r"(\d+) (passed|failed|skipped|errors?|warnings?)\b", text)
    ]
    nodes = re.findall(r"(?m)^(?:FAILED|ERROR) (tests/[^\s]+|tests\\[^\s]+)", text)
    summary = {
        "at": started.isoformat(),
        "phase": phase,
        "command": command,
        "cwd": str(cwd),
        "exit": result.returncode,
        "seconds": round((datetime.now(UTC) - started).total_seconds(), 3),
        "counts": counts,
        "failedNodeIds": nodes,
        "expectedFailure": expect_failure,
        "testedSources": sources,
        "privateOriginal": {
            "path": str(raw),
            "sha256": sha(result.stdout),
            "bytes": len(result.stdout),
        },
    }
    with (OUT / "checks.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, ensure_ascii=False) + "\n")
    data = read()
    data["runs"].append(summary)
    write(data)
    print(
        json.dumps(
            {k: summary[k] for k in ("phase", "exit", "seconds", "counts", "failedNodeIds")}
        ),
        flush=True,
    )
    assert (result.returncode != 0) if expect_failure else (result.returncode == 0)
    return result


def integrity():
    data = read()
    allowed = set(
        PRODUCTS
        + TESTS
        + DOCS
        + [str((OUT / p).relative_to(ROOT)).replace("\\", "/") for p in ARTIFACTS]
    )
    changed = set(git("diff", "--name-only").decode().splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
    assert not changed - allowed
    assert not git("diff", "--cached", "--name-only").strip()
    assert git("rev-parse", "HEAD").decode().strip() == BASE
    old_changed = [
        r["path"]
        for r in data["priorEvidenceBaseline"]
        if sha((ROOT / r["path"]).read_bytes()) != r["sha256"]
    ]
    other_sources = [
        r["path"]
        for r in data["sourceBaseline"]
        if r["path"] not in PRODUCTS + TESTS and sha((ROOT / r["path"]).read_bytes()) != r["sha256"]
    ]
    assert not old_changed and not other_sources
    return {
        "changedApprovedFiles": sorted(changed),
        "oldEvidenceChecked": len(data["priorEvidenceBaseline"]),
        "oldEvidenceChanged": [],
        "outsideApproval": [],
        "headUnchanged": True,
    }


if __name__ == "__main__":
    if sys.argv[1] == "baseline":
        baseline()
    elif sys.argv[1] == "integrity":
        print(json.dumps(integrity()))
