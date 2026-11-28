"""Real services with an explicitly synthetic parent seed; no login/PG claim."""
import asyncio
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.clients.catalog_client import CatalogClient
from app.clients.llm_client import LlmClient
from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.consultation_parent import ConsultationParent, ParentTask
from app.services.chat_service import ChatService
from app.services.skincare_recommendation_tool import SkincareRecommendationTool

logging.disable(logging.CRITICAL)
events = []
dispatches = []
original_send = httpx.AsyncClient.send


async def observed_send(self, request, *args, **kwargs):
    local = request.url.host in {"127.0.0.1", "localhost"}
    event = {"kind": "local_http" if local else "remote_model", "method": request.method,
             "host": request.url.host, "path": request.url.path,
             "at": datetime.now(timezone.utc).isoformat()}
    payload = json.loads(request.content) if request.content else None
    if local:
        event["query"] = str(request.url.query, "utf-8")
        event["input"] = payload
    elif payload:
        event["model"] = payload.get("model")
        event["tools"] = [t.get("function", {}).get("name") for t in payload.get("tools", [])]
        event["stage"] = payload.get("text", {}).get("format", {}).get("name")
    events.append(event)
    try:
        response = await original_send(self, request, *args, **kwargs)
        event["status"] = response.status_code
        if not local and request.url.path.endswith("chat/completions"):
            await response.aread()
            event["modelResponse"] = response.json().get("choices", [])
        if local:
            await response.aread()
            event["responseSha256"] = hashlib.sha256(response.content).hexdigest()
            body = response.json()
            event["responseKeys"] = list(body) if isinstance(body, dict) else []
            if isinstance(body, dict):
                event["productCount"] = len(body.get("products", []))
                event["candidateCount"] = len(body.get("candidates", []))
                for key in ("version", "dataVersion", "snapshotId", "embeddingInputTokens"):
                    if key in body:
                        event[key] = body[key]
        return response
    except BaseException as exc:
        event["errorType"] = type(exc).__name__
        raise


class ObservedService(ChatService):
    async def _dispatch_parent_read(self, capability, req):
        entry = {"capability": capability, "inputMessage": req.message}
        dispatches.append(entry)
        response = await super()._dispatch_parent_read(capability, req)
        entry["answer"] = response.answer
        entry["products"] = [p.model_dump(mode="json", by_alias=True) for p in response.products]
        entry["knowledgeStatus"] = response.knowledge.status if response.knowledge else None
        return response


async def main():
    mode = sys.argv[1]
    info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
    env = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
    assert env["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    config = get_settings()
    config.g8_enabled = True
    config.g1_supervisor_enabled = True
    config.g5_enabled = True
    if mode in {"knowledge", "mixed"}:
        private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
        config.g5_openai_api_key = private["G5_OPENAI_API_KEY"]
        config.g5_internal_token = private["G5_INTERNAL_TOKEN"]
        config.catalog_api_url = "http://127.0.0.1:19838"
    llm = LlmClient(env["LLM_BASE_URL"], env["LLM_API_KEY"], env["LLM_MODEL"], 80)
    catalog_url = "http://127.0.0.1:19834"
    service = ObservedService(None, llm, CatalogClient(catalog_url),
        skincare=SkincareRecommendationTool(SkincareRecommendationClient(catalog_url)))
    parent = ConsultationParent(tasks=[ParentTask(goal="style", objective="기존 룩 검색", version=1,
        status="completed")])
    questions = (["토너 찾아줘. 크림도 찾아줘", "보습용 크림으로 찾아줘. 토너는 그대로 둬", "크림은 2만 원 이하로 찾아줘", "크림 대신 로션으로 바꿔줘", "상품 종류 제한은 풀고 예산은 유지해줘"] if mode == "product" else
        ["세안 후 보습 순서를 설명해줘. 자외선 차단제를 덧바르는 방법도 설명해줘"])
    if mode == "mixed":
        questions = ["세안 후 보습 순서를 설명해줘. 보습용 크림도 찾아줘."]
    label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "final"
    if "--holdout" in sys.argv:
        questions = ["토너 찾아줘. 크림도 찾아줘", "토너 쪽은 놔두고 크림만 촉촉한 걸로", "그쪽은 15,000원을 넘지 않게 해줘"]
    if "--broad" in sys.argv:
        questions = ["립 제품 찾아줘. 베이스 제품도 찾아줘"]
    followup = "--followup" in sys.argv
    if followup:
        previous = json.loads((OUT / "common-parent-product-contract-product.json").read_text(encoding="utf-8"))
        parent = ConsultationParent.model_validate(previous["turns"][-1]["parent"])
        questions = ["보습용 크림으로 찾아줘. 토너는 그대로 둬"]
    httpx.AsyncClient.send = observed_send
    record = {"mode": mode, "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "at": datetime.now(timezone.utc).isoformat(), "uncommitted": True,
              "parentSeed": "synthetic completed style task; not restored from PG",
              "catalog": "live HTTP 19834", "modelConfiguredMode": "live",
              "pg": "NOT_RUN", "loginApp": "NOT_RUN", "turns": []}
    for question in questions:
        events.clear()
        dispatches.clear()
        req = ChatRequest(message=question, locale="ko")
        req._consultation_parent = parent
        turn = {"question": question}
        try:
            result = await service.answer(req)
            turn["response"] = result.model_dump(mode="json", by_alias=True)
            turn["parent"] = result._consultation_parent.model_dump(mode="json", by_alias=True) if result._consultation_parent else None
            turn["taskResults"] = [r.model_dump(mode="json", by_alias=True) for r in result._task_results]
            parent = result._consultation_parent or parent
        except BaseException as exc:
            turn["errorType"] = type(exc).__name__
        turn.update(events=list(events), dispatches=list(dispatches), intentAudit=req._parent_intent_audit,
                    actualRemoteHttpCalls=sum(e["kind"] == "remote_model" for e in events),
                    embeddingCallsInApi="not instrumented; search telemetry only")
        record["turns"].append(turn)
    if followup:
        record["parentSeed"] = "restored previous real service result from evidence JSON; no PG"
    path = OUT / f"common-parent-product-contract-{label}-{mode}{'-followup' if followup else ''}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"record": path.name, "turns": [{"question": t["question"],
        "answer": t.get("response", {}).get("answer"), "errorType": t.get("errorType"),
        "remoteCalls": t["actualRemoteHttpCalls"], "dispatches": len(t["dispatches"])} for t in record["turns"]]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
