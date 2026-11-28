"""Source-bound N02 review fixes: scan all new artifacts and append a fresh trace."""
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
source = json.loads((OUT / "n02-scope-sources.json").read_text())
for item in source["sources"]:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
reports = {}
for name in ["n02-scope-mock.xml", "n02-scope-live-pg-final.xml", "n02-scope-pg-regression-final.xml", "n02-scope-backend-final.xml"]:
    suite = ET.parse(OUT / name).find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0"
    reports[name] = dict(suite.attrib)
root = ET.parse(OUT / "n02-scope-live-pg-final.xml")
live = {name: json.loads(root.find(".//property[@name='" + name + "']").get("value"))
        for name in ["scope_live_catalog", "scope_pg_roundtrip"]}
record = {
    "case": "G8-N02-SCOPED-DECLARATIONS-OPTION-LEVEL-GOAL-FOLLOWUP",
    "recordedAt": datetime.now(timezone(timedelta(hours=9))).isoformat(),
    "head": source["head"], "uncommitted": True,
    "stage": "5-collaboration", "workBundle": "1-of-6 N02 review fixes",
    "sourceSha256": source["sources"], "sourceByteBasis": "worktree-exact",
    "sourceDiff": "reports/g8/parent/n02-scope-source.diff", "junit": reports,
    "liveEvidence": live,
    "modelConfiguredMode": "disabled or mock per turn", "actualExternalModelCalls": 0,
    "validation": {"typecheck": "PASS", "appLint": "PASS", "ruff": "PASS", "importContracts": 3,
                   "appJest": "NOT_RUN", "browser": "NOT_RUN", "expoGo": "NOT_RUN", "liveLLM": "NOT_RUN"},
    "commands": ["uv run pytest tests/test_g8_owned_look.py tests/test_g8_consultation_parent.py -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/n02-scope-mock.xml",
                 "uv run python ../../reports/g8/parent/n02-scope-run-pg.py",
                 "uv run python ../../reports/g8/parent/n02-scope-run-pg.py --regression",
                 "uv run pytest -q --tb=short -o junit_family=legacy --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-scope-final-all --junitxml=../../reports/g8/parent/n02-scope-backend-final.xml",
                 "uv run ruff check .", "uv run lint-imports", "npm run typecheck", "npm run lint"],
    "security": {"version": "8.30.1", "ignore": "empty", "result": "PASS"},
    "remainingBundles": ["E01", "B01", "parent replanning/cancel/resume", "real user flows", "full evaluation and review"],
    "limitations": ["Actual Catalog uses synthetic inventory and no PG; the separate actual PG case uses mock Catalog/auth.",
                    "Only explicit catalog-bound expressions are resolved; arbitrary ellipsis and fuzzy product matching remain unsupported.",
                    "General option-price consultation and mixed zone-wide exception release remain future scope."],
    "prCreated": False,
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
(OUT / "n02-scope-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
inputs = json.loads((OUT / "n02-scope-security-inputs.json").read_text())
with tempfile.TemporaryDirectory(prefix="g8-scope-scan-") as folder:
    target = Path(folder)
    for name in inputs:
        source_path = (ROOT / name).resolve()
        assert source_path.is_relative_to(ROOT)
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    scan = subprocess.run([str(SCANNER), "dir", str(target), "--config", str(ROOT / ".gitleaks.toml"),
                          "--gitleaks-ignore-path", str(empty), "--redact", "--no-banner"], capture_output=True, text=True)
    (OUT / "n02-scope-security.log").write_text(scan.stdout + scan.stderr, encoding="utf-8")
    if scan.returncode: raise SystemExit("Security scan failed; findings withheld")
print("Gitleaks 8.30.1 empty ignore PASS:", len(inputs), "files")
trace = OUT / "trace.jsonl"
before = json.loads((OUT / "n02-scope-trace-before.json").read_text())
data = trace.read_bytes()
assert len(data) == before["bytes"] and hashlib.sha256(data).hexdigest() == before["sha256"]
append_record(trace, record, scanner=SCANNER, config=ROOT / ".gitleaks.toml")
assert trace.read_bytes()[:before["bytes"]] == data
print("Appended 1 scanned record; historical rows preserved:", before["lines"])
