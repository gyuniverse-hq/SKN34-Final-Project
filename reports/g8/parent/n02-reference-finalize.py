"""Verify exact source bytes, scan new evidence, preserve historical trace prefix."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import append_record
SCANNER = Path("/var/tmp/g8-gitleaks-audit-20261126/gitleaks")
source = json.loads((OUT / "n02-reference-sources.json").read_text())
for item in source["sources"]:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
reports = {}
for name in ["n02-reference-interpreter-final.xml", "n02-reference-mock.xml", "n02-reference-live-final.xml", "n02-reference-live-pg-final.xml", "n02-reference-pg-regression-2.xml", "n02-reference-backend-final.xml"]:
    suite = ET.parse(OUT / name).find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0", name
    reports[name] = dict(suite.attrib)
def property_value(file, name):
    value = ET.parse(OUT / file).find(".//property[@name='" + name + "']")
    assert value is not None, name
    return json.loads(value.get("value"))
record = {
    "case":"G8-N02-REFERENCE-AND-ZONE-EXCEPTION",
    "recordedAt":datetime.now(timezone(timedelta(hours=9))).isoformat(),
    "head":source["head"], "uncommitted":True, "stage":"5-collaboration", "workBundle":"1-of-6 N02",
    "sourceSha256":source["sources"], "sourceByteBasis":"worktree-exact",
    "sourceDiff":"reports/g8/parent/n02-reference-source.diff",
    "newSourceSnapshot":"reports/g8/parent/n02-reference-new-sources.json",
    "sourceNote":"Full backend/PG run before test-only line wrapping; preformat manifest preserved. Final interpreter rerun verifies final test file. Runtime source unchanged.",
    "junit":reports,
    "liveModel":property_value("n02-reference-live-final.xml", "reference_live"),
    "livePostgres":property_value("n02-reference-live-pg-final.xml", "reference_pg"),
    "liveCatalog":property_value("n02-reference-live-pg-final.xml", "scope_live_catalog"),
    "validation":{"ruff":"PASS", "importContracts":3, "typecheck":"PASS", "appLint":"PASS",
                  "combinedLiveModelCatalogPG":"NOT_RUN", "appJest":"NOT_RUN", "browser":"NOT_RUN", "expoGo":"NOT_RUN", "humanReview":"NOT_RUN"},
    "history":["Initial live run failed to apply exemption; original proposal was not captured, cause unconfirmed. Explicit exempt/status prompt followed by passing second and final runs.",
               "Initial full backend test had 17 Windows temp-directory permission errors; dedicated basetemp rerun passed.",
               "Initial PG regression found the price unit man-won matched exception particle; fixed with regression and full PG rerun."],
    "commands":["backend/chatbot/.venv/Scripts/python.exe -B reports/g8/parent/n02-reference-run-live.py",
                "backend/chatbot/.venv/Scripts/python.exe -B reports/g8/parent/n02-reference-run-pg.py",
                "backend/chatbot/.venv/Scripts/python.exe -B reports/g8/parent/n02-reference-run-pg.py --regression",
                "uv run pytest -q --tb=short --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-reference-final-all --junitxml=../../reports/g8/parent/n02-reference-backend-final.xml",
                "uv run pytest tests/test_g8_owned_look_interpreter.py -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/n02-reference-interpreter-final.xml",
                "uv run ruff check .", "uv run lint-imports", "npm run typecheck", "npm run lint"],
    "remainingBundles":["E01", "B01", "parent execution lifecycle", "real user flows", "full evaluation and review"],
    "security":{"version":"8.30.1", "ignore":"empty", "result":"PASS"},
    "prCreated":False, "pushed":False,
}
def inspect(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in {"authorization", "access_token", "refresh_token", "api_key", "password", "faceimage", "facevideo"}
            inspect(child)
    elif isinstance(value, list):
        for child in value: inspect(child)
    elif isinstance(value, str):
        assert "-----BEGIN PRIVATE KEY-----" not in value
inspect(record)
(OUT / "n02-reference-record.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
paths = [ROOT / item["path"] for item in source["sources"]]
paths += [ROOT / "docs/ai-design/G8-IMPLEMENTATION-SPEC.md", ROOT / "docs/ai-design/G8-WORKLOG.md"]
paths += list(OUT.glob("n02-reference-*"))
paths = [p for p in paths if p.name not in {"n02-reference-security.log", "n02-reference-finalize.log"}]
with tempfile.TemporaryDirectory(prefix="g8-reference-scan-") as folder:
    target = Path(folder)
    for path in paths:
        dest = target / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    scan = subprocess.run([str(SCANNER),"dir",str(target),"--config",str(ROOT / ".gitleaks.toml"),"--gitleaks-ignore-path",str(empty),"--redact","--no-banner"],capture_output=True,text=True)
    (OUT / "n02-reference-security.log").write_text(scan.stdout+scan.stderr,encoding="utf-8")
    if scan.returncode: raise SystemExit("Security scan failed; findings withheld")
print("Gitleaks 8.30.1 empty ignore PASS:",len(paths),"files")
trace=OUT / "trace.jsonl"
before=json.loads((OUT / "n02-reference-trace-before.json").read_text())
data=trace.read_bytes()
assert len(data)==before["bytes"] and hashlib.sha256(data).hexdigest()==before["sha256"]
append_record(trace,record,scanner=SCANNER,config=ROOT / ".gitleaks.toml")
assert trace.read_bytes()[:before["bytes"]]==data
print("Appended 1 scanned record; historical rows preserved:",before["lines"])
