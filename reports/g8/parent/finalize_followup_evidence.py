"""Scan the approved change set and append one source-bound G8 evidence record."""
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
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import append_record

OUT = ROOT / "reports/g8/parent"
SCANNER = Path("/var/tmp/g8-gitleaks-audit-20261126/gitleaks")
inputs = json.loads((OUT / "followup-option-security-inputs.json").read_text())
with tempfile.TemporaryDirectory(prefix="g8-followup-scan-") as folder:
    target = Path(folder)
    for name in inputs:
        source = (ROOT / name).resolve()
        assert source.is_relative_to(ROOT)
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    scan = subprocess.run([str(SCANNER), "dir", str(target), "--config", str(ROOT / ".gitleaks.toml"),
        "--gitleaks-ignore-path", str(empty), "--redact", "--no-banner"], capture_output=True, text=True)
    (OUT / "followup-option-security.log").write_text(scan.stdout + scan.stderr, encoding="utf-8")
    if scan.returncode:
        raise SystemExit("Security scan did not pass; findings withheld")
print("Gitleaks 8.30.1 passed with empty ignore; files:", len(inputs))
if "--scan-only" in sys.argv:
    raise SystemExit(0)
source = json.loads((OUT / "followup-option-sources.json").read_text(encoding="utf-8"))
for item in source["sources"]:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
reports = {}
for name in ["followup-option-mock.xml", "followup-option-chatbot-all.xml", "followup-option-live-pg.xml", "followup-option-pg-regression.xml"]:
    suite = ET.parse(OUT / name).find("testsuite")
    assert suite is not None and suite.attrib["failures"] == "0" and suite.attrib["errors"] == "0"
    reports[name] = dict(suite.attrib)
prop = ET.parse(OUT / "followup-option-live-pg.xml").find(".//property[@name='option_memory_evidence']")
app = json.loads((OUT / "followup-option-app-tests.json").read_text(encoding="utf-8"))
assert app["success"]
record = {
    "case": "G8-PARENT-FOLLOWUP-SALE-OPTION-MEMORY",
    "recordedAt": datetime.now(timezone(timedelta(hours=9))).isoformat(),
    "stage": "5-collaboration-partial", "head": source["head"], "uncommitted": True,
    "sourceSha256": source["sources"], "sourceByteBasis": "worktree-exact",
    "diff": "reports/g8/parent/followup-option-source.diff",
    "newSource": "reports/g8/parent/followup-option-new-source.json",
    "junit": reports, "app": {"passed": app["numPassedTests"], "suites": app["numPassedTestSuites"]},
    "liveCatalogAndPg": json.loads(prop.attrib["value"]),
    "browser": {"tool": "Aside", "mode": "live-web-DOM-guest", "artifact": "reports/g8/parent/followup-option-browser.json", "submittedUtterances": 0},
    "security": {"version": "8.30.1", "mode": "changed-files-plus-new-record", "ignore": "empty", "result": "PASS"},
    "commands": ["uv run pytest -q --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-followup-option-all --junitxml=../../reports/g8/parent/followup-option-chatbot-all.xml --tb=short",
        "uv run python ../../reports/g8/parent/run_option_memory_pg.py",
        "uv run python ../../reports/g8/parent/run_option_memory_pg.py --regression",
        "npm run typecheck", "npm run lint",
        "npm test -- --runInBand __tests__/routes.test.ts __tests__/chatProducts.test.ts __tests__/chatProductDetail.test.tsx __tests__/chatConversationStore.test.ts __tests__/chatScreen.test.ts __tests__/styleRecipeResult.test.tsx __tests__/styleRecipeFlow.test.tsx --json --outputFile=reports/g8/parent/followup-option-app-tests.json",
        "uv run ruff check .", "uv run lint-imports"],
    "notRun": ["live LLM", "Expo Go", "authenticated app full memory-consent journey", "full G8 E01/B01", "generic cancellation/resume"],
    "scopeNote": "The final live-test change adds per-turn mock call counters only; runtime sources match the full regression run. No commits, push or PR."
}
append_record(OUT / "trace.jsonl", record, scanner=SCANNER, config=ROOT / ".gitleaks.toml")
print("Source identities verified; scanned record appended")
