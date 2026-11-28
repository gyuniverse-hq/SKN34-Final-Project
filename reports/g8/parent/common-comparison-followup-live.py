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

CASES = ["비교 대상만 다른 크림으로 바꿔줘", "비교 대상은 다슈 맨즈 아쿠아 리얼 모이스트 올인원크림으로 바꿔줘", "다슈 맨즈 아쿠아 리얼 모이스트 올인원크림", "그 비교만 바꿔줘", "토너 찾아줘. 크림도 찾아줘", "비교는 그만해줘"]
def request(index):
    from app.schemas.consultation_parent import ParentQuestion
    tasks=[ParentTask(task_id="comparison", goal="product", product_operation="compare", objective="기준 상품과 다른 상품 가격 비교", status="waiting_user", version=1), ParentTask(task_id="look",goal="style",objective="데일리 룩",status="completed",version=1)]
    if index == 3: tasks.append(ParentTask(task_id="comparison-two",goal="product",product_operation="compare",objective="립 제품 두 개 비교",status="completed",version=1))
    req=ChatRequest(message=CASES[index],locale="ko")
    req._consultation_parent=ConsultationParent(tasks=tasks)
    if index==2: req._consultation_parent.question=ParentQuestion(task_id="comparison",goal="product",version=1,text="어떤 제품과 비교할까요?",input_key="selection")
    return req

def passes(index,intent):
    if intent is None: return False
    updates={c.task_id for c in intent.changes if c.operation=="update"}
    if index<=2: return intent.action=="continue" and updates=={"comparison"} and not intent.additions and all(c.operation!="withdraw" for c in intent.changes)
    if index==3: return intent.action=="clarify" and not intent.changes and not intent.additions
    if index==4: return len(intent.additions)==2 and not updates and all(a.product_operation=="search" for a in intent.additions)
    return (intent.action in {"withdraw","cancel"} and intent.targets==["comparison"]) or (intent.action=="continue" and {c.task_id for c in intent.changes if c.operation=="withdraw"}=={"comparison"} and not updates and not intent.additions)

async def main():
    values = json.loads(subprocess.check_output(["docker","inspect","vishue-chatbot-1"],text=True))[0]["Config"]["Env"]
    env = dict(v.split("=",1) for v in values if "=" in v)
    assert env["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    assert env["LLM_MODEL"] == "gpt-6-luna"
    base = LlmClient(env["LLM_BASE_URL"],env["LLM_API_KEY"],env["LLM_MODEL"],80)
    class Recorder:
        configured=True
        async def complete_with_tools(self,*args,**kwargs):
            result=await base.complete_with_tools(*args,**kwargs)
            self.proposal=json.loads(result[0]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
            return result
    llm=Recorder()
    get_settings().g8_enabled = True
    contract = json.dumps({"prompt":PROMPT,"schema":ConsultationIntent.model_json_schema(by_alias=True)},ensure_ascii=False,sort_keys=True)
    (OUT/"common-comparison-followup-live-contract.json").write_text(contract,encoding="utf-8")
    rows=[]
    for repetition in range(3):
        for index in range(6):
            req=request(index)
            control=await prepare_turn(req,llm)
            rows.append({"at":datetime.now(timezone.utc).isoformat(),"case":index+1,"repetition":repetition+1,"utterance":req.message,"modelConfiguredMode":"live","actualModelCalls":(req._parent_intent_audit or {}).get("invocations",0),"model":env["LLM_MODEL"],"contractSha256":hashlib.sha256(contract.encode()).hexdigest(),"proposal":llm.proposal,"audit":req._parent_intent_audit,"passed":passes(index,req._parent_intent),"answer":control.answer if control else None,"catalog":"NOT_RUN","pg":"NOT_RUN"})
            (OUT/"common-comparison-followup-live.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Repetition",repetition+1,"pass",sum(r["passed"] for r in rows[-6:]),"/6",flush=True)
    if hasattr(llm,"aclose"): await llm.aclose()
    return 0 if all(r["passed"] for r in rows) else 1

raise SystemExit(asyncio.run(main()))

