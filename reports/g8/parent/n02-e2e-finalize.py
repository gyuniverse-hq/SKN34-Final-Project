"""Verify source identity and scan evidence before appending one historical record."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
SCANNER = Path("/var/tmp/g8-gitleaks-audit-20261126/gitleaks")
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import append_record

source = json.loads((OUT / "n02-e2e-sources.json").read_text())
for item in source["sources"]:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
tests = {}
for name in ["n02-e2e-backend-last.xml", "n02-e2e-pg-regression-2.xml"]:
    suite = ET.parse(OUT / name).find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0"
    tests[name] = dict(suite.attrib)
rows = [json.loads(line) for line in (OUT / "n02-e2e-turns.jsonl").read_text().splitlines()]
runtime = json.loads((OUT / "n02-e2e-runtime.json").read_text())
final = rows[runtime["finalSourceStartRow"]:runtime["finalSourceStartRow"]+3]
assert [len(row["modelCalls"]) for row in final] == [0,1,0]
record = {"case":"G8-N02-REAL-AUTH-WEB-PARTIAL", "at":datetime.now(timezone.utc).isoformat(),
          "head":source["head"], "uncommitted":True,"stage":"5-collaboration", "bundle":"1-of-6",
          "sourceSha256":source["sources"], "sourceDiff":"reports/g8/parent/n02-e2e-source.diff",
          "newSources":"reports/g8/parent/n02-e2e-new-sources.json", "tests":tests,
          "live":{"auth":"real_supabase","catalog":"live_local_api","postgres":"live_isolated",
                  "modelConfigured":"live", "model":"gpt-6-luna", "finalCallsPerTurn":[0,1,0],
                  "allRecordedCalls":sum(len(row["modelCalls"]) for row in rows),
                  "finalSourceStartRow":runtime["finalSourceStartRow"],"turnEvidence":"reports/g8/parent/n02-e2e-turns.jsonl",
                  "pgEvidence":"reports/g8/parent/n02-e2e-pg-final.json","browserEvidence":"reports/g8/parent/n02-e2e-browser.txt"},
          "validation":{"n02InitialFollowupBudget":"PASS","pgAnswersOptionsExceptions":"PASS",
                        "appCardDisplay":"PASS","recentConversationRestore":"BLOCKED_LOADING",
                        "restoredCardDetail":"NOT_RUN","expoGo":"NOT_RUN","appJest":"NOT_RUN",
                        "ruff":"PASS","importContracts":3,"typecheck":"PASS","lint":"PASS",
                        "overallLoggedInAppE2E":"PARTIAL"},
          "limitations":["Some recipe products have unconfirmed options and usage relations.",
                         "Intermediate model requested confirmation; final run resolved the referent directly.",
                         "Memory-off generic chat retry returned 503 in an exploratory PG test; unresolved, explicit N02 denial passes.",
                         "Browser reload creates a new look entry; recent conversation opening remained loading."],
          "security":{"scanner":"gitleaks 8.30.1","ignore":"empty","result":"PASS"},
          "prCreated":False,"pushed":False}
record_path = OUT / "n02-e2e-record.json"
record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
paths = [ROOT / item["path"] for item in source["sources"]]
paths += [ROOT / "docs/ai-design/G8-WORKLOG.md", ROOT / "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"]
paths += [p for p in OUT.glob("n02-e2e-*") if p.name not in {"n02-e2e-security.log","n02-e2e-finalize.log"}]
with tempfile.TemporaryDirectory(prefix="g8-e2e-scan-") as folder:
    target = Path(folder)
    for path in paths:
        dest = target / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    scan = subprocess.run([str(SCANNER),"dir",str(target),"--config",str(ROOT / ".gitleaks.toml"),
                           "--gitleaks-ignore-path",str(empty),"--redact","--no-banner"],capture_output=True,text=True)
    (OUT / "n02-e2e-security.log").write_text(scan.stdout+scan.stderr,encoding="utf-8")
    if scan.returncode: raise SystemExit("Security scan failed; findings withheld")
trace = OUT / "trace.jsonl"
before = trace.read_bytes()
assert not any(json.loads(line).get("case") == record["case"] for line in before.splitlines())
append_record(trace,record,scanner=SCANNER,config=ROOT / ".gitleaks.toml")
assert trace.read_bytes()[:len(before)] == before
print("PASS",len(paths),"files; historical trace rows preserved",len(before.splitlines()),"new rows 1")
