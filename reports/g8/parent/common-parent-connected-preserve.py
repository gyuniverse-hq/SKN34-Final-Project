"""Preserve tested source, actual calls, and failed acceptance checks without credentials."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


previous = json.loads((OUT / "common-parent-ids-sources.json").read_text())
for item in previous:
    if item["path"].startswith("backend/"):
        assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"], item["path"]
paths = [item["path"] for item in previous]
paths.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in OUT.glob("common-parent-connected-*.py"))
sources = [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in sorted(set(paths))]
(OUT / "common-parent-connected-source.diff").write_bytes(git("diff", "--", "backend/chatbot", "docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"))
records = [json.loads((OUT / f"common-parent-connected-{name}.json").read_text(encoding="utf-8")) for name in ["product", "product-followup", "knowledge", "mixed"]]
assert sum(t["actualRemoteHttpCalls"] for r in records for t in r["turns"]) == 17
from dotenv import dotenv_values
private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
private.update(dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v))
secrets = [v for k, v in private.items() if v and len(v) >= 12 and any(term in k for term in ("KEY", "TOKEN", "PASSWORD", "DATABASE_URL"))]
for p in OUT.glob("common-parent-connected-*"):
    content = p.read_text(encoding="utf-8")
    assert not any(secret in content for secret in secrets), "Credential match; values withheld"
record = {"case": "G8-PARENT-CONNECTED-REAL-ANSWERS", "at": datetime.now(timezone.utc).isoformat(),
    "head": git("rev-parse", "HEAD").decode().strip(), "uncommitted": True, "stage": "5-collaboration",
    "sourceSha256": sources, "diff": "reports/g8/parent/common-parent-connected-source.diff",
    "untrackedSources": "reports/g8/parent/common-parent-ids-new-sources.json (unchanged hashes verified)",
    "modelConfiguredMode": "live", "actualRemoteHttpCalls": 17,
    "modelCalls": {"gpt-6-luna": 8, "gpt-6.1-terra": 9},
    "embeddingRemoteCalls": "not instrumented in API; 3 search telemetry records only",
    "catalog": "real HTTP; 4 product requests; 4991 rows each; payload digests in evidence",
    "g5": "real integration DB search/context; 3 searches; evidence sourceVersion in JSON",
    "parentSeed": "synthetic completed style task; followup uses previous actual result JSON",
    "validation": {"realServiceWiring": "PASS", "targetedTaskReuse": "PASS", "productTypeFit": "FAIL",
        "semanticCompletion": "FAIL: product marked completed for non-cream candidates",
        "knowledgeCoverage": "PARTIAL", "mockTests": "48 PASS; 4 XML format warnings",
        "typecheck": "PASS", "lint": "PASS", "loginApp": "NOT_RUN", "conversationPG": "NOT_RUN",
        "fullG8": "NOT_RUN"},
    "evidence": [f"reports/g8/parent/common-parent-connected-{name}.json" for name in ["product", "product-followup", "knowledge", "mixed"]],
    "security": {"knownCredentialMatch": "none", "gitleaks": "PASS only after finalizer success", "ignore": "empty"},
    "temporaryRelayAndApi": "stopped after validation", "prCreated": False, "pushed": False}
(OUT / "common-parent-connected-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved source; 17 actual calls; acceptance failures recorded; no known credential matches")
