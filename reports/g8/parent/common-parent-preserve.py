"""Preserve exact uncommitted source and executed regression evidence."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

new = git("ls-files", "--others", "--exclude-standard", "--", "backend/chatbot").decode().splitlines()
paths = sorted(set(git("diff", "--name-only", "--", "backend/chatbot").decode().splitlines() + new + [
    "docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"
]))
sources = [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths]
(OUT / "common-parent-sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
(OUT / "common-parent-source.diff").write_bytes(git("diff", "--", *paths))
(OUT / "common-parent-new-sources.json").write_text(json.dumps([
    {"path": p, "content": (ROOT / p).read_text(encoding="utf-8")} for p in new
], ensure_ascii=False, indent=2), encoding="utf-8")
suites = {}
for name in ["backend", "pg"]:
    suite = ET.parse(OUT / f"common-parent-{name}.xml").find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0"
    suites[name] = dict(suite.attrib)
live = [json.loads((OUT / name).read_text(encoding="utf-8")) for name in
        ["common-parent-live-initial.json", "common-parent-live-second.json", "common-parent-live.json"]]
assert [sum(row["passed"] for row in run) for run in live] == [2, 3, 4]
assert sum(row["actualModelCalls"] for run in live for row in run) == 12
record = {
    "case": "G8-COMMON-PARENT-LIFECYCLE-B1", "at": datetime.now(timezone.utc).isoformat(),
    "head": git("rev-parse", "HEAD").decode().strip(), "uncommitted": True,
    "stage": "5-collaboration", "step": "B shared execution boundary and lifecycle; general planning still pending",
    "sourceSha256": sources, "diff": "reports/g8/parent/common-parent-source.diff",
    "newSources": "reports/g8/parent/common-parent-new-sources.json",
    "validation": {"suites": suites, "modelConfiguredMode": "mock regressions / live interpreter",
        "actualExternalModelCalls": 12, "catalog": "mock",
        "storage": "real isolated PostgreSQL vishue_chat_test; auth/model/catalog mock",
        "liveModel": "4/4 final interpreter only; initial 2/4 and second 3/4 retained", "liveCatalog": "NOT_RUN", "loginApp": "NOT_RUN",
        "ruff": "PASS", "imports": "3 PASS", "typecheck": "PASS", "lint": "PASS",
        "fullG8": "NOT_RUN", "humanReview": "NOT_RUN"},
    "commands": ["uv run ruff check .", "uv run lint-imports", "uv run pytest -q --tb=short -o junit_family=legacy --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-common-parent-final2 --junitxml=../../reports/g8/parent/common-parent-backend.xml",
        "uv run python ../../reports/g8/parent/common-parent-run-pg.py --regression", "npm run typecheck", "npm run lint"],
    "liveEvidence": ["reports/g8/parent/common-parent-live-initial.json", "reports/g8/parent/common-parent-live-second.json", "reports/g8/parent/common-parent-live.json"],
    "remaining": ["general goal planning", "transitive condition invalidation", "combined withdrawal and retained work", "shared answer", "full G8 E2E"],
    "security": {"scanner": "8.30.1", "ignore": "empty", "result": "PASS only after finalizer success"},
    "prCreated": False, "pushed": False,
}
(OUT / "common-parent-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved source and successful backend/PG suites", len(sources))
