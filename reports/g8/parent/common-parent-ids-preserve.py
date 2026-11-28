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
(OUT / "common-parent-ids-sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
(OUT / "common-parent-ids-source.diff").write_bytes(git("diff", "--", *paths))
(OUT / "common-parent-ids-new-sources.json").write_text(json.dumps([
    {"path": p, "content": (ROOT / p).read_text(encoding="utf-8")} for p in new
], ensure_ascii=False, indent=2), encoding="utf-8")
suites = {}
for name in ["backend", "pg"]:
    suite = ET.parse(OUT / ("common-parent-ids-backend-final.xml" if name == "backend" else "common-parent-ids-pg.xml")).find("testsuite")
    assert suite.get("failures") == suite.get("errors") == "0"
    suites[name] = dict(suite.attrib)
import sys
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.schemas.consultation_parent import ConsultationIntent
from app.services.consultation_intent_service import PROMPT
live = json.loads((OUT / "common-parent-ids-live.json").read_text(encoding="utf-8"))
frozen = json.loads((OUT / "common-parent-ids-live-contract.json").read_text(encoding="utf-8"))
assert frozen == {"prompt": PROMPT, "schema": ConsultationIntent.model_json_schema(by_alias=True)}
assert len(live) == 12 and all(r["passed"] for r in live)
assert sum(r["actualModelCalls"] for r in live) == 12
assert len({r["contractSha256"] for r in live}) == 1
record = {
    "case": "G8-PARENT-NEW-GOALS-BY-TASK-ID", "at": datetime.now(timezone.utc).isoformat(),
    "head": git("rev-parse", "HEAD").decode().strip(), "uncommitted": True,
    "stage": "5-collaboration", "step": "B independent goal additions and task-ID execution; C/D pending",
    "sourceSha256": sources, "diff": "reports/g8/parent/common-parent-ids-source.diff",
    "newSources": "reports/g8/parent/common-parent-ids-new-sources.json",
    "validation": {"suites": suites, "modelConfiguredMode": "mock regressions / live frozen interpreter",
        "actualExternalModelCalls": 12, "catalog": "mock",
        "storage": "real isolated PostgreSQL vishue_chat_test; auth/model/catalog mock",
        "liveModel": "12/12 on four synthetic inputs repeated three times; not E2E", "liveCatalog": "NOT_RUN", "loginApp": "NOT_RUN",
        "ruff": "PASS", "imports": "3 PASS", "typecheck": "PASS", "lint": "PASS",
        "fullG8": "NOT_RUN", "humanReview": "NOT_RUN"},
    "commands": ["uv run ruff check .", "uv run lint-imports", "uv run pytest -q --tb=short -o junit_family=legacy --basetemp=C:/Users/playdata2/AppData/Local/Temp/g8-parent-ids-final --junitxml=../../reports/g8/parent/common-parent-ids-backend-final.xml",
        "uv run python ../../reports/g8/parent/common-parent-ids-run-pg.py --regression", "npm run typecheck", "npm run lint"],
    "liveEvidence": "reports/g8/parent/common-parent-ids-live.json",
    "liveContract": "reports/g8/parent/common-parent-ids-live-contract.json",
    "model": "gpt-6-luna", "modelSnapshot": "not separately pinned",
    "fixtureData": "synthetic Catalog and knowledge fixture-v1; no live Catalog data",
    "remaining": ["held-out model validation", "login app selection/cards", "shared answer", "original full G8 evaluation"],
    "security": {"scanner": "8.30.1", "ignore": "empty", "result": "PASS only after finalizer success"},
    "prCreated": False, "pushed": False,
}
(OUT / "common-parent-ids-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved source and successful backend/PG suites", len(sources))
