"""Scan new G8 evidence; preserve the historical trace byte-for-byte."""
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
source = json.loads((OUT / "n02-needs-sources.json").read_text())
for item in source["sources"]:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
inputs = json.loads((OUT / "n02-needs-security-inputs.json").read_text())
assert "reports/g8/parent/trace.jsonl" not in inputs
with tempfile.TemporaryDirectory(prefix="g8-needs-scan-") as folder:
    target = Path(folder)
    for name in inputs:
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT)
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    scan = subprocess.run([str(SCANNER), "dir", str(target), "--config", str(ROOT / ".gitleaks.toml"),
        "--gitleaks-ignore-path", str(empty), "--redact", "--no-banner"], capture_output=True, text=True)
    (OUT / "n02-needs-security.log").write_text(scan.stdout + scan.stderr, encoding="utf-8")
    if scan.returncode:
        raise SystemExit("Security scan failed; findings withheld")
print("Gitleaks 8.30.1 / empty ignore PASS:", len(inputs), "files")
if "--scan-only" in sys.argv:
    raise SystemExit(0)
reports = {}
for name in ["n02-needs-mock-final.xml", "n02-needs-live-pg-final.xml",
             "n02-needs-pg-regression-final.xml", "n02-needs-temp-retry.xml", "n02-needs-backend.xml"]:
    suite = ET.parse(OUT / name).find("testsuite")
    if name != "n02-needs-backend.xml":
        assert suite.get("failures") == suite.get("errors") == "0"
    reports[name] = dict(suite.attrib)
root = ET.parse(OUT / "n02-needs-live-pg-final.xml")
live = {name: json.loads(root.find(".//property[@name='" + name + "']").get("value"))
        for name in ["same_zone_live_catalog", "item_question_pg_roundtrip"]}
record = {
    "case": "G8-N02-PER-ITEM-COVERAGE-PARENT-OUTCOME",
    "recordedAt": datetime.now(timezone(timedelta(hours=9))).isoformat(),
    "stage": "5-collaboration-partial", "head": source["head"], "uncommitted": True,
    "sourceSha256": source["sources"], "sourceByteBasis": "worktree-exact",
    "diff": "reports/g8/parent/n02-needs-source.diff", "junit": reports,
    "liveEvidence": live,
    "modelConfiguredMode": "disabled or mock (per turn)", "actualExternalModelCalls": 0,
    "validation": {"appTypecheck": "PASS", "appLint": "PASS", "ruff": "PASS", "importContracts": 3,
                   "appJest": "NOT_RUN", "browser": "NOT_RUN", "expoGo": "NOT_RUN", "liveLLM": "NOT_RUN"},
    "security": {"version": "8.30.1", "ignore": "empty", "result": "PASS", "changedFiles": len(inputs)},
    "commands": ["uv run pytest tests/test_g8_owned_look.py tests/test_g8_consultation_parent.py -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/n02-needs-mock-final.xml",
                 "uv run python ../../reports/g8/parent/run_n02_needs_pg.py",
                 "uv run python ../../reports/g8/parent/run_n02_needs_pg.py --regression",
                 "uv run pytest -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/n02-needs-backend.xml",
                 "uv run pytest tests/test_g1_e5_live_driver.py tests/test_g1_evaluation.py tests/test_g1_human_review_materials.py -q --tb=short -o junit_family=legacy --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-needs-regression-retry --junitxml=../../reports/g8/parent/n02-needs-temp-retry.xml",
                 "npm run typecheck", "npm run lint", "uv run ruff check .", "uv run lint-imports"],
    "limitations": ["Whole backend run: 1532 passed, 109 skipped, 17 temporary-directory errors; affected files rerun 38 passed, not a single whole-suite PASS.",
                    "Live inventory is synthetic; actual Catalog source is not evidence of joint use or substitution.",
                    "Historical PG regression errors were question-text expectations, updated to the product-scoped contract.",
                    "Whole N02/E01/B01 and generic replanning/cancel/resume remain incomplete."]
}
# Detect unsafe field names/secret markers without printing their values.
def inspect(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in {"authorization", "access_token", "refresh_token", "api_key", "password", "faceimage", "facevideo"}
            inspect(child)
    elif isinstance(value, list):
        for child in value:
            inspect(child)
    elif isinstance(value, str):
        assert "-----BEGIN PRIVATE KEY-----" not in value
inspect(record)
trace = OUT / "trace.jsonl"
before = json.loads((OUT / "n02-needs-trace-before.json").read_text())
data = trace.read_bytes()
assert len(data) == before["bytes"] and hashlib.sha256(data).hexdigest() == before["sha256"]
append_record(trace, record, scanner=SCANNER, config=ROOT / ".gitleaks.toml")
assert trace.read_bytes()[:before["bytes"]] == data
print("New trace scanned and appended; historical rows preserved:", before["lines"])
