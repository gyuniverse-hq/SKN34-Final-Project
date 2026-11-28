"""Six approved synthetic cases, three repetitions of a frozen model contract."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.consultation_parent import ConsultationParent, ParentTask, ConsultationIntent
from app.services.consultation_intent_service import PROMPT, prepare_turn

CASES = ["토너 찾아줘. 크림도 찾아줘", "비교는 그대로 두고 세럼도 찾아줘", "비교 대상만 다른 크림으로 바꿔줘", "비교는 그만하고 토너 찾아줘", "크림만 15,000원 이하로 바꿔줘", "그것만 바꿔줘"]
def request(index):
    tasks = [ParentTask(task_id="comparison", goal="product", product_operation="compare", objective="이 제품과 토리든 립 에센스를 비교하고 데일리 룩도 찾아줘", status="waiting_user", version=1), ParentTask(task_id="look", goal="style", objective="데일리 룩 찾아줘", status="completed", version=1)]
    if index >= 4:
        tasks += [ParentTask(task_id="task-"+kind, goal="product", product_operation="search", objective=label+" 찾아줘", status="completed", version=1) for kind,label in [("toner","토너"),("cream","크림")]]
    req = ChatRequest(message=CASES[index], locale="ko")
    req._consultation_parent = ConsultationParent(tasks=tasks)
    return req

def passes(index, intent):
    if intent is None: return False
    updates = {c.task_id for c in intent.changes if c.operation == "update"}
    withdrawals = {c.task_id for c in intent.changes if c.operation == "withdraw"}
    additions = intent.additions
    if index in (0,1,3):
        count = 2 if index == 0 else 1
        terms = ["토너","크림"] if index == 0 else ["세럼"] if index == 1 else ["토너"]
        return (intent.action == "continue" and len(additions) == count and not updates
            and withdrawals == ({"comparison"} if index == 3 else set())
            and all(a.capability == "product" and a.product_operation == "search" for a in additions)
            and all(sum(term in a.quote for a in additions) == 1 for term in terms))
    if index == 2:
        return intent.action == "continue" and updates == {"comparison"} and not withdrawals and not additions and next(c for c in intent.changes if c.operation=="update").product_operation == "compare"
    if index == 4:
        return intent.action == "continue" and updates == {"task-cream"} and not withdrawals and not additions
    return intent.action == "clarify" and not intent.changes and not additions

async def main():
    values = json.loads(subprocess.check_output(["docker","inspect","vishue-chatbot-1"],text=True))[0]["Config"]["Env"]
    env = dict(v.split("=",1) for v in values if "=" in v)
    assert env["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    assert env["LLM_MODEL"] == "gpt-6-luna"
    llm = LlmClient(env["LLM_BASE_URL"],env["LLM_API_KEY"],env["LLM_MODEL"],80)
    get_settings().g8_enabled = True
    contract = json.dumps({"prompt":PROMPT,"schema":ConsultationIntent.model_json_schema(by_alias=True)},ensure_ascii=False,sort_keys=True)
    (OUT/"common-goal-binding-live-contract.json").write_text(contract,encoding="utf-8")
    rows=[]
    for repetition in range(3):
        for index in range(6):
            req=request(index)
            control=await prepare_turn(req,llm)
            rows.append({"at":datetime.now(timezone.utc).isoformat(),"case":index+1,"repetition":repetition+1,"utterance":req.message,"modelConfiguredMode":"live","actualModelCalls":(req._parent_intent_audit or {}).get("invocations",0),"model":env["LLM_MODEL"],"contractSha256":hashlib.sha256(contract.encode()).hexdigest(),"audit":req._parent_intent_audit,"passed":passes(index,req._parent_intent),"answer":control.answer if control else None,"catalog":"NOT_RUN","pg":"NOT_RUN"})
            (OUT/"common-goal-binding-live.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Repetition",repetition+1,"pass",sum(r["passed"] for r in rows[-6:]),"/6",flush=True)
    if hasattr(llm,"aclose"): await llm.aclose()
    return 0 if all(r["passed"] for r in rows) else 1

raise SystemExit(asyncio.run(main()))

