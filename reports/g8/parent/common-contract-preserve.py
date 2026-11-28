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
(OUT / "common-contract-sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
(OUT / "common-contract-source.diff").write_bytes(git("diff", "--", *paths))
(OUT / "common-contract-new-sources.json").write_text(json.dumps([
    {"path": p, "content": (ROOT / p).read_text(encoding="utf-8")} for p in new
], ensure_ascii=False, indent=2), encoding="utf-8")
suites = {}
for name in ["backend", "pg"]:
    suite = ET.parse(OUT / f"common-contract-{name}.xml").find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0"
    suites[name] = dict(suite.attrib)
record = {
    "case": "G8-COMMON-TASK-CONTRACT-A", "at": datetime.now(timezone.utc).isoformat(),
    "head": git("rev-parse", "HEAD").decode().strip(), "uncommitted": True,
    "stage": "5-collaboration", "step": "A common result adapters; B/C/D pending",
    "sourceSha256": sources, "diff": "reports/g8/parent/common-contract-source.diff",
    "newSources": "reports/g8/parent/common-contract-new-sources.json",
    "validation": {"suites": suites, "modelConfiguredMode": "mock",
        "actualExternalModelCalls": 0, "catalog": "mock",
        "storage": "real isolated PostgreSQL vishue_chat_test; auth/model/catalog mock",
        "liveModel": "NOT_RUN", "liveCatalog": "NOT_RUN", "loginApp": "NOT_RUN",
        "ruff": "PASS", "imports": "3 PASS", "typecheck": "PASS", "lint": "PASS",
        "fullG8": "NOT_RUN", "humanReview": "NOT_RUN"},
    "commands": ["uv run ruff check .", "uv run lint-imports", "uv run pytest -q --tb=short -o junit_family=legacy --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-common-backend --junitxml=../../reports/g8/parent/common-contract-backend.xml",
        "uv run python ../../reports/g8/parent/common-contract-run-pg.py --regression", "npm run typecheck", "npm run lint"],
    "security": {"scanner": "8.30.1", "ignore": "empty", "result": "PASS only after finalizer success"},
    "prCreated": False, "pushed": False,
}
(OUT / "common-contract-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved source and successful backend/PG suites", len(sources))
