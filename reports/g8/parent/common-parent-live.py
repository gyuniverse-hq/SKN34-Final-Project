"""Four explicitly approved synthetic utterances; no user records or source documents."""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.consultation_parent import ConsultationParent, ParentTask
from app.services.consultation_intent_service import prepare_turn

async def main():
    info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
    env = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
    assert env["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    assert env["LLM_MODEL"] == "gpt-6-luna"
    llm = LlmClient(env["LLM_BASE_URL"], env["LLM_API_KEY"], env["LLM_MODEL"], 80)
    get_settings().g8_enabled = True
    cases = [
        ("아까 못 마친 쪽만 이어서 해 줘", "retry", ["style"]),
        ("이 상담은 여기서 멈춰", "cancel", ["product", "style"]),
        ("중단한 룩 찾기부터 이어 줘", "resume", ["style"]),
        ("향료 제외 조건만 해제하고 예산은 유지해 줘", "continue", []),
    ]
    records = []
    for text, expected, targets in cases:
        req = ChatRequest(message=text, locale="ko")
        req._consultation_parent = ConsultationParent(tasks=[
            ParentTask(goal="product", version=1, status="completed"),
            ParentTask(goal="style", version=1, status="failed"),
        ])
        if expected == "resume":
            req._consultation_parent.execution_state = "cancelled"
            for task in req._consultation_parent.tasks: task.status = "cancelled"
        if expected == "continue":
            req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="skin", version=1, status="partial")])
        response = await prepare_turn(req, llm)
        intent = req._parent_intent
        passed = bool(intent and intent.action == expected and (not targets or set(intent.targets) == set(targets)))
        records.append({"at": datetime.now(timezone.utc).isoformat(), "utterance": text,
            "modelConfiguredMode": "live", "model": env["LLM_MODEL"], "destination": "api.openai.com/v1",
            "actualModelCalls": req._parent_intent_audit["invocations"],
            "expectedAction": expected, "audit": req._parent_intent_audit,
            "controlAnswer": response.answer if response else None, "passed": passed,
            "catalog": "NOT_RUN", "pg": "NOT_RUN", "app": "NOT_RUN"})
    (ROOT / "reports/g8/parent/common-parent-live.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Live interpreter:", sum(r["passed"] for r in records), "/", len(records), "calls:", sum(r["actualModelCalls"] for r in records))
    return 0 if all(r["passed"] for r in records) else 1

raise SystemExit(asyncio.run(main()))
