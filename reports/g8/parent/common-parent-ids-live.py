"""Approved four synthetic utterances, three repetitions of one frozen prompt/schema."""
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.consultation_parent import ConsultationIntent, ConsultationParent, ParentTask
from app.services.consultation_intent_service import PROMPT, prepare_turn

OUT = ROOT / "reports/g8/parent"
CASES = [
    "세안 후 보습 순서를 설명해줘. 자외선 차단제를 덧바르는 방법도 설명해줘",
    "토너 찾아줘. 크림도 찾아줘",
    "덧바르는 방법만 다시 설명해줘",
    "보습 설명은 빼고 차단제는 덧바르기도 설명해줘",
]

def request(index):
    if index < 2:
        tasks = [ParentTask(goal="product" if index == 0 else "knowledge", version=1,
                    status="completed", objective="기존 상품 비교" if index == 0 else "기존 관리 원인 설명")]
    else:
        tasks = [ParentTask(task_id="task-moisture", goal="knowledge", version=1,
                    status="completed", objective="세안 후 보습 순서를 설명해줘"),
                 ParentTask(task_id="task-sunscreen", goal="knowledge", version=1,
                    status="failed" if index == 2 else "completed",
                    objective="자외선 차단제를 덧바르는 방법도 설명해줘")]
    req = ChatRequest(message=CASES[index], locale="ko")
    req._consultation_parent = ConsultationParent(plan_id=UUID("11111111-1111-4111-8111-111111111111"), tasks=tasks)
    return req

def passes(index, intent):
    if intent is None:
        return False
    if index < 2:
        capability = "knowledge" if index == 0 else "product"
        terms = ["보습", "덧바르"] if index == 0 else ["토너", "크림"]
        return (intent.action == "continue" and len(intent.additions) == 2
                and all(a.capability == capability for a in intent.additions)
                and all(sum(term in a.quote for a in intent.additions) == 1 for term in terms)
                and not intent.changes)
    if index == 2:
        return intent.action == "retry" and intent.targets == ["task-sunscreen"] and not intent.additions
    return (intent.action == "continue" and not intent.additions and
            {(c.task_id, c.operation) for c in intent.changes} ==
            {("task-moisture", "withdraw"), ("task-sunscreen", "update")})

async def main():
    info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
    env = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
    assert env["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    assert env["LLM_MODEL"] == "gpt-6-luna"
    llm = LlmClient(env["LLM_BASE_URL"], env["LLM_API_KEY"], env["LLM_MODEL"], 80)
    get_settings().g8_enabled = True
    contract = {"prompt": PROMPT, "schema": ConsultationIntent.model_json_schema(by_alias=True)}
    frozen = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(frozen.encode()).hexdigest()
    (OUT / "common-parent-ids-live-contract.json").write_text(frozen, encoding="utf-8")
    records = []
    for repetition in range(3):
        for index in range(4):
            req = request(index)
            result = await prepare_turn(req, llm)
            audit = req._parent_intent_audit or {}
            records.append({"at": datetime.now(timezone.utc).isoformat(), "case": index + 1,
                "repetition": repetition + 1, "utterance": req.message,
                "modelConfiguredMode": "live", "model": env["LLM_MODEL"],
                "actualModelCalls": audit.get("invocations", 0), "destination": "api.openai.com/v1",
                "contractSha256": digest, "audit": audit, "passed": passes(index, req._parent_intent),
                "controlAnswer": result.answer if result else None,
                "catalog": "NOT_RUN", "pg": "NOT_RUN", "app": "NOT_RUN"})
            (OUT / "common-parent-ids-live.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Repetition", repetition + 1, "passed", sum(r["passed"] for r in records[-4:]), "/4", flush=True)
    print("Total", sum(r["passed"] for r in records), "/12; external calls", sum(r["actualModelCalls"] for r in records), flush=True)
    return 0 if all(r["passed"] for r in records) else 1

raise SystemExit(asyncio.run(main()))
