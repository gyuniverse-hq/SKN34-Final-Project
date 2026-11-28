"""Seal evaluation evidence even when product evaluation fails; append only after security PASS."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "stage6-web-eval-"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def manifest(paths):
    return [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)} for path in paths]

baseline = json.loads((OUT / (PREFIX + "baseline.json")).read_text(encoding="utf-8"))
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == baseline["head"]
approved_docs = {"docs/ai-design/G8-IMPLEMENTATION-SPEC.md", "docs/ai-design/G8-WORKLOG.md"}
product_sources = [entry for entry in baseline["source"] if entry["path"] not in approved_docs]
assert all(sha(ROOT / entry["path"]) == entry["sha256"] for entry in product_sources), "Product or related test source changed"
rows = [json.loads(line) for line in (OUT / (PREFIX + "app-turns.jsonl")).read_text(encoding="utf-8").splitlines()]
for row in rows:
    source = json.loads((OUT / row["sourceSnapshot"]).read_text(encoding="utf-8"))
    assert all(sha(ROOT / entry["path"]) == entry["sha256"] for entry in source)
review = json.loads((OUT / (PREFIX + "review.json")).read_text(encoding="utf-8"))
assert review["overall"].startswith("FAIL"), "Do not promote actual failures to PASS"
pg = json.loads((OUT / (PREFIX + "pg-review.json")).read_text(encoding="utf-8"))
assert all(pg["checks"].values())
tests = []
for name in ("contract", "pg", "memory-pg"):
    path = OUT / (PREFIX + name + ".xml")
    suites = list(ET.parse(path).getroot().iter("testsuite"))
    values = {key: sum(int(suite.get(key, "0")) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
    assert values["failures"] == values["errors"] == 0
    tests.append({"name": name, "mode": "mock contracts" if name == "contract" else "actual PostgreSQL; mock main models/auth; Catalog mode per case XML", **values, "timestamps": [suite.get("timestamp") for suite in suites]})
events = [json.loads(line) for line in (OUT / (PREFIX + "model-events.jsonl")).read_text(encoding="utf-8").splitlines()]
starts = [event for event in events if event["event"] == "start"]
assert len(starts) == sum(len(row.get("modelCalls", [])) for row in rows)
assert len(starts) == 34
g5 = [json.loads(line) for line in (OUT / (PREFIX + "g5-models.jsonl")).read_text(encoding="utf-8").splitlines()]
stopped = {}
for host, port in [("127.0.0.1", 19833), ("127.0.0.1", 19838), ("172.24.16.240", 19841)]:
    with socket.socket() as sock:
        sock.settimeout(2)
        stopped[str(port)] = sock.connect_ex((host, port)) != 0
assert all(stopped.values())
(OUT / (PREFIX + "source.diff")).write_bytes(subprocess.check_output(["git", "diff", "--binary", "HEAD", "--", "backend/chatbot", "app", "hooks", "lib", "store", "types", "__tests__"]))
spec = importlib.util.spec_from_file_location("runtime", OUT / (PREFIX + "runtime.py"))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
env = runtime.environment()
secrets = [value for key, value in env.items() if any(token in key for token in ["PASSWORD", "API_KEY", "INTERNAL_TOKEN"]) and isinstance(value, str) and len(value) >= 8]
from sqlalchemy.engine import make_url
import psycopg
for name in ["DATABASE_URL", "CHAT_DATABASE_URL"]:
    password = make_url(env[name]).password
    if password and len(password) >= 8:
        secrets.append(password)
url = make_url(env["CHAT_DATABASE_URL"]).set(drivername="postgresql")
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    principals = [entry[0] for entry in conn.execute("SELECT DISTINCT owner_id FROM chat_conversations")]
empty = OUT / (PREFIX + "empty.ignore")
empty.write_bytes(b"")
artifacts = [path for path in sorted(OUT.glob(PREFIX + "*")) if path.is_file() and path.name not in {PREFIX + "record.json", PREFIX + "security.log"}]
docs = [ROOT / "docs/ai-design/G8-IMPLEMENTATION-SPEC.md", ROOT / "docs/ai-design/G8-WORKLOG.md"]
payload = b"\n".join(path.read_bytes() for path in artifacts + docs)
assert not any(value.encode() in payload or value.encode("utf-16-le") in payload for value in secrets), "Credential match; values withheld"
assert not any(value.encode() in payload for value in principals if len(value) >= 16), "Account identifier match; values withheld"
linux_root = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
scanner = ["wsl", "-d", "vishue-g5", "--", "/var/tmp/g8-gitleaks-audit-20261126/gitleaks"]
assert subprocess.check_output(scanner + ["version"]).strip() == b"8.30.1"
command = scanner + ["stdin", "--config", linux_root + "/.gitleaks.toml", "--gitleaks-ignore-path", linux_root + "/reports/g8/parent/" + empty.name, "--redact", "--no-banner"]
scan = subprocess.run(command, input=payload, capture_output=True)
(OUT / (PREFIX + "security.log")).write_bytes(scan.stdout + scan.stderr)
assert scan.returncode == 0, "Security check failed; no append; sensitive values withheld"
record = {
    "case": "G8-STAGE6-WEB-AGENT-REVIEW", "at": datetime.now(timezone.utc).isoformat(),
    "head": baseline["head"], "branch": baseline["branch"], "uncommitted": True,
    "developLocalRef": subprocess.check_output(["git", "rev-parse", "origin/develop"], text=True).strip(), "remoteFreshnessChecked": False,
    "stage": "⑥ first actual web evaluation FAIL; reopen broken stage ⑤ criteria 1/3/4/5",
    "productSourceUnchanged": True, "sourceSha256": product_sources, "managementDocs": manifest(docs),
    "evaluationStatus": "FAIL", "reviewMode": review["policy"],
    "actual": {"modelConfiguredMode": "live", "appExecutions": len(rows), "answers": sum("answer" in row for row in rows), "errors": sum("errorCode" in row for row in rows), "generationHttpStarts": len(starts), "unattributedModelStarts": 0, "embeddingHttpStarts": sum(event["event"] == "start" and event["path"] == "/v1/embeddings" for event in g5), "models": ["gpt-6-luna", "gpt-6.1-terra", "text-embedding-3-large"], "providerSnapshotId": "not collected", "catalogGlobalSnapshot": "not frozen; per-response versions retained", "pgChecks": pg["checks"], "temporaryListenersClosed": stopped},
    "testSuites": tests, "appChecks": {"typecheck": "PASS", "lint": "PASS", "frontendProductEdits": 0},
    "security": {"status": "PASS", "scanner": "8.30.1", "ignore": "empty", "inputsScanned": len(artifacts + docs), "findings": 0, "knownCredentialComparison": "PASS", "principalIdentifierComparison": "PASS"},
    "findings": review["findings"], "notRun": review["notRun"], "artifacts": manifest(artifacts),
    "tracePreservation": {"previousRows": baseline["previousTraceRows"], "previousSha256": baseline["previousTraceSha256"]}
}
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import normalize_record
record = normalize_record(record)
record_path = OUT / (PREFIX + "record.json")
record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
check = subprocess.run(command, input=line, capture_output=True)
assert check.returncode == 0, "Final record scan failed; no append"
if "--append" in sys.argv:
    trace = OUT / "trace.jsonl"
    before = trace.read_bytes()
    assert sha(trace) == baseline["previousTraceSha256"]
    assert len(before.splitlines()) == baseline["previousTraceRows"]
    assert not any(json.loads(row).get("case") == record["case"] for row in before.splitlines())
    with trace.open("ab") as stream:
        stream.write(line)
    assert trace.read_bytes() == before + line
    print("PASS evidence integrity/security; appended exactly one record; product evaluation remains FAIL")
else:
    print("PASS evidence integrity/security preflight; trace unchanged; product evaluation FAIL")
