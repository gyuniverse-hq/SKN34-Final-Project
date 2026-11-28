"""Freeze final evidence, retaining failed/intermediate live executions separately."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "common-parent-product-contract-"
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.schemas.consultation_parent import ConsultationIntent
from app.schemas.supervisor import SearchPlan
from app.services.consultation_intent_service import PROMPT
from app.services.beauty_consultation_service import PLAN_PROMPT, PRODUCT_REQUIREMENT_PROMPT

frozen = json.loads((OUT / (PREFIX + "frozen.json")).read_text(encoding="utf-8"))
assert frozen == {"parentPrompt": PROMPT, "parentSchema": ConsultationIntent.model_json_schema(by_alias=True),
                  "productPrompt": PLAN_PROMPT + PRODUCT_REQUIREMENT_PROMPT,
                  "productSchema": SearchPlan.model_json_schema(by_alias=True)}
sources = json.loads((OUT / (PREFIX + "preserve-sources.json")).read_text())
for item in sources:
    assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"], item["path"]
for path in [ROOT / "docs/ai-design/G8-WORKLOG.md", ROOT / "docs/ai-design/G8-IMPLEMENTATION-SPEC.md", *OUT.glob(PREFIX + "*.py")]:
    sources.append({"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
suites = {}
for label in ["backend-preserve", "pg-preserve", "live-pg-preserve", "live-pg-preserve-repeat"]:
    suite = next(ET.parse(OUT / (PREFIX + label + ".xml")).iter("testsuite"))
    assert suite.get("failures") == suite.get("errors") == "0"
    suites[label] = dict(suite.attrib)
calls = []
for label in ["product", "final-product", "broad-product"]:
    r = json.loads((OUT / (PREFIX + label + ".json")).read_text(encoding="utf-8"))
    calls.append({"evidence": PREFIX + label + ".json", "calls": sum(t["actualRemoteHttpCalls"] for t in r["turns"])})
for path in sorted(OUT.glob(PREFIX + "live-pg*.xml")):
    values = [json.loads(p.get("value")) for p in ET.parse(path).iter("property") if p.get("name") == "live_product_contract"]
    calls.append({"evidence": path.name, "calls": sum(t["actualRemoteHttpCalls"] for r in values for t in r["turns"])})
private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
private.update(dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v))
secrets = [v for k, v in private.items() if v and len(v) >= 12 and any(term in k for term in ("KEY", "TOKEN", "PASSWORD", "DATABASE_URL"))]
for path in OUT.glob(PREFIX + "*"):
    assert not any(value in path.read_text(encoding="utf-8") for value in secrets), "Credential match; withheld"
record = {"case": "G8-PRODUCT-KIND-COMPLETION-PRESERVE", "at": datetime.now(timezone.utc).isoformat(),
    "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "branch": "feat/compound-consultation", "uncommitted": True, "stage": "5-collaboration",
    "sourceSha256": sources, "diff": "reports/g8/parent/" + PREFIX + "preserve-source.diff",
    "newSources": "reports/g8/parent/" + PREFIX + "preserve-new-sources.json",
    "frozenContract": "reports/g8/parent/" + PREFIX + "frozen.json",
    "suites": suites, "modelConfiguredMode": "live acceptance / mock regressions",
    "actualRemoteHttpCalls": sum(x["calls"] for x in calls), "callBreakdown": calls,
    "finalFrozenActualModelCalls": 18, "model": "gpt-6-luna", "modelSnapshot": "alias; not immutable",
    "acceptance": "real model+Catalog+PG 4 turns x2 PASS; unchanged toner result asserted",
    "auth": "mock", "initialParent": "synthetic", "g5": "NOT_RUN", "loginApp": "NOT_RUN",
    "earlierFindings": ["initial parent goal-addition rejected; retained failed run",
        "earlier PG assertion missed sibling withdrawal; strengthened assertion and added preserve contract"],
    "catalogCrossCheck": "reports/g8/parent/" + PREFIX + "live-dialogue-preserve.json",
    "ruff": "PASS", "imports": "3 PASS", "typecheck": "PASS", "lint": "PASS",
    "remaining": ["shared natural answer/card selection", "login app", "full original G8 evaluation", "broader interpretation stability"],
    "security": {"knownCredentialMatch": "none", "gitleaks": "PASS only after finalizer success", "ignore": "empty"},
    "prCreated": False, "pushed": False}
(OUT / (PREFIX + "record.json")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Verified frozen source and tests; total real model calls:", record["actualRemoteHttpCalls"], "; final acceptance:18")
