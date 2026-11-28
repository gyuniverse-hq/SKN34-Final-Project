"""Nine fixed synthetic question-scope proposals; no real user history or credentials saved."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
spec = importlib.util.spec_from_file_location("runtime", OUT / "stage5-closeout-app-run.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
os.environ.update(runtime.environment())
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.clients.llm_client import get_llm_client
from app.services.consultation_intent_service import prepare_turn, PROMPT
from app.schemas.consultation_parent import ConsultationIntent
from app.schemas.owned_look_intent import LookReferenceSnapshot, LookReferenceTarget
from app.services.owned_look_interpreter import interpret
from tests.test_g8_consultation_intent import question_scope_request
import httpx

async def main():
    records, events = [], []
    filename = sys.argv[1] if len(sys.argv) > 1 else "question-scope-answer-model.json"
    assert filename.startswith("question-scope-answer-") and "/" not in filename
    def preserve_event(value):
        with (OUT / (Path(filename).stem + "-events.jsonl")).open("a", encoding="utf-8") as f:
            f.write(json.dumps(value,ensure_ascii=False) + "\n")
    client = get_llm_client()
    original_complete = client.complete_with_tools
    proposals = []
    async def complete(*args, **kwargs):
        result = await original_complete(*args, **kwargs)
        proposals.append(json.loads(result[0]["choices"][0]["message"]["tool_calls"][0]
                                    ["function"]["arguments"]))
        preserve_event({"event":"proposal","value":proposals[-1]})
        return result
    client.complete_with_tools = complete
    original = httpx.AsyncClient.send
    async def send(self, request, *args, **kwargs):
        if request.url.host == "api.openai.com":
            events.append({"event": "start", "at": datetime.now(timezone.utc).isoformat(),
                           "model": json.loads(request.content).get("model")})
            preserve_event(events[-1])
        response = await original(self, request, *args, **kwargs)
        if request.url.host == "api.openai.com":
            events.append({"event": "end", "at": datetime.now(timezone.utc).isoformat(),
                           "status": response.status_code})
            preserve_event(events[-1])
        return response
    httpx.AsyncClient.send = send
    texts = [
        "삐아 07웜베이지는 없어. 그 상품 보유 여부에 답한 거야. 롬앤 질문과 피부 상담 결과는 그대로 둬",
        "삐아 팔레트는 없고, 롬앤은 나중에 답할게. 피부 설명은 유지해줘.",
        "피부 설명은 그대로 두고, 컨투어 질문은 남겨 둬. 아이팔레트는 안 갖고 있어.",
    ]
    for index, text in enumerate(texts):
        for repeat in range(3):
            req = question_scope_request()
            req.message = text
            req._consultation_parent.pending_questions[0].text = "삐아 아이팔레트 07웜베이지를 가지고 있나요?"
            req._consultation_parent.pending_questions[1].text = "롬앤 컨투어 02그레이쿨을 가지고 있나요?"
            answer = await prepare_turn(req, client)
            intent = req._parent_intent
            interpretation, applied = [], []
            refs = LookReferenceSnapshot(version="synthetic-snapshot-v1",recipe_version="recipe-v1",
                targets=[LookReferenceTarget(target_id=key, product_id=key, option_id=key+"-option",
                    label=label, zone=zone) for key,label,zone in
                    [("bbia","삐아 07웜베이지","eyeshadow"),("romand","롬앤 02그레이쿨","contour")]])
            for q, quote in req._question_answers:
                plan, audit = await interpret(quote, refs, q, client, answering_question=True)
                interpretation.append(audit)
                if plan.action == "update":
                    applied.extend((op.target_id, op.scope, op.status) for op in plan.operations)
            ok = bool(intent and applied == [("bbia", "option", "missing")] and
                      {(c.task_id, c.operation) for c in intent.changes} ==
                      {("task-look", "update"), ("task-skin", "preserve")} and
                      all(a[0] != "romand" for a in applied))
            records.append({"case": index+1, "repeat": repeat+1, "utterance": text,
                            "mode": "live", "passed": ok, "audit": req._parent_intent_audit,
                            "questionInterpretation": interpretation, "appliedDeclarations": applied,
                            "proposal": proposals[-1], "answer": answer.answer if answer else None})
            (OUT / filename).write_text(json.dumps({
                "configuredMode": "live", "promptSha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
                "schemaSha256": hashlib.sha256(json.dumps(ConsultationIntent.model_json_schema(),sort_keys=True).encode()).hexdigest(),
                "records": records, "actualHttpStarts": sum(e["event"] == "start" for e in events),
                "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(index+1, repeat+1, "PASS" if ok else "FAIL", flush=True)
    assert all(r["passed"] for r in records), "Some fixed proposals failed; all attempts preserved"

asyncio.run(main())
