"""Local real-auth browser verification. Credentials never enter files or argv."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
DB = "vishue_g8_browser"
PORTS = {"api":19834,"chat":19833,"web":19836}

def container_env(name):
    value = json.loads(subprocess.check_output(["docker","inspect",name],text=True))[0]
    return dict(v.split("=",1) for v in value["Config"]["Env"] if "=" in v)

def environment():
    from sqlalchemy.engine import make_url
    api, chat = container_env("vishue-api-1"), container_env("vishue-chatbot-1")
    base = dict(os.environ, PYTHONUTF8="1", ENV="local", LOG_LEVEL="WARNING",
                CORS_ORIGINS=json.dumps(["http://localhost:19836"]), SKINCARE_REFRESH_ENABLED="false")
    for key in ["SUPABASE_URL","SUPABASE_PUBLISHABLE_KEY"]:
        base[key] = api[key]
    url = make_url(api["DATABASE_URL"]).set(host="127.0.0.1",port=15434)
    base["DATABASE_URL"] = url.render_as_string(hide_password=False)
    base["CHAT_DATABASE_URL"] = url.set(database=DB).render_as_string(hide_password=False)
    for key in ["LLM_BASE_URL","LLM_MODEL","LLM_API_KEY"]:
        base[key] = chat[key]
    for key in ["NEO4J_USER", "NEO4J_PASSWORD"]:
        if chat.get(key): base[key] = chat[key]
    base["NEO4J_URI"] = "bolt://127.0.0.1:17687"
    base["G1_SUPERVISOR_ENABLED"] = "true"
    assert base["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    from urllib.parse import urlsplit
    redis = urlsplit(chat["REDIS_URL"])
    auth = redis.netloc.rsplit("@",1)[0]+"@" if "@" in redis.netloc else ""
    base["REDIS_URL"] = redis._replace(netloc=auth+"127.0.0.1:16379").geturl()
    base.update(CATALOG_API_URL="http://127.0.0.1:19834", G8_ENABLED="true",
                G7_PERSISTENCE_ENABLED="true", G7_MEMORY_ENABLED="true",
                G7_STRUCTURED_MEMORY_ENABLED="true", G5_ENABLED="false")
    from dotenv import dotenv_values
    private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
    for key in ("INGREDIENT_MAPPING_PATH", "INGREDIENT_ALIAS_APPROVALS_PATH"):
        if private.get(key):
            base[key] = private[key]
    for key in ("G5_OPENAI_API_KEY", "G5_INTERNAL_TOKEN"):
        base[key] = private[key]
    base.update(G5_ENABLED="true")
    return base

def init_db(env):
    import psycopg
    from sqlalchemy.engine import make_url
    url=make_url(env["CHAT_DATABASE_URL"]).set(drivername="postgresql")
    assert url.database == DB
    with psycopg.connect(url.set(database="postgres").render_as_string(hide_password=False),autocommit=True) as conn:
        if not conn.execute("select 1 from pg_database where datname=%s",(DB,)).fetchone():
            conn.execute("CREATE DATABASE vishue_g8_browser")
    for args in [["-m","alembic","upgrade","head"],["-m","app.jobs.init_chat_checkpoints"]]:
        subprocess.run([sys.executable,*args],cwd=ROOT/"backend/chatbot",env=env,check=True)

def start():
    env=environment()
    init_db(env)
    processes={}
    for role in ["api","chat"]:
        directory=ROOT/"backend"/("chatbot" if role=="chat" else "api")
        python=directory/".venv/Scripts/python.exe"
        log=open(OUT/f"question-scope-answer-app-{role}.log","ab")
        proc=subprocess.Popen([str(python),"-B",str(Path(__file__).resolve()),role],cwd=directory,env=env,
                              stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        processes[role]=proc.pid
    web=dict(os.environ,PYTHONUTF8="1",CI="1",EXPO_NO_TELEMETRY="1",
             EXPO_PUBLIC_API_BASE_URL="http://localhost:19834",
             EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833",
             EXPO_PUBLIC_SUPABASE_URL=env["SUPABASE_URL"],
             EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env["SUPABASE_PUBLISHABLE_KEY"])
    log=open(OUT/"question-scope-answer-app-web.log","ab")
    proc=subprocess.Popen(["node","node_modules/expo/bin/cli","start","--web","--port","19836","--localhost"],
                          cwd=ROOT,env=web,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    processes["web"]=proc.pid
    (OUT/"question-scope-answer-app-runtime.json").write_text(json.dumps({"ports":PORTS,"pids":processes,"chatDatabase":DB,
        "auth":"real_supabase", "model":env["LLM_MODEL"],"g5Enabled":False,
        "startedAt":datetime.now(timezone.utc).isoformat()},indent=2),encoding="utf-8")
    print("Started isolated runtime",processes,flush=True)

def serve(role):
    directory=ROOT/"backend"/("chatbot" if role=="chat" else "api")
    sys.path.insert(0,str(directory))
    import uvicorn
    from app.main import create_app
    if role=="chat":
        import hashlib
        source_paths=sorted((ROOT/"backend/chatbot/app").rglob("*.py"))
        source_snapshot=OUT/f"question-scope-answer-live-source-{datetime.now(timezone.utc).strftime('%H%M%S')}.json"
        source_snapshot.write_text(json.dumps([{"path":p.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in source_paths],indent=2),encoding="utf-8")
        import httpx
        from app.clients.knowledge_client import KnowledgeClient
        original_knowledge_init = KnowledgeClient.__init__
        def knowledge_init(self, http):
            http.base_url = httpx.URL("http://127.0.0.1:19838/internal/knowledge/")
            original_knowledge_init(self, http)
        KnowledgeClient.__init__ = knowledge_init
        from app.clients.llm_client import LlmClient
        from app.services.chat_service import ChatService
        calls=ContextVar("e2e_calls",default=None)
        reads=ContextVar("catalog_reads",default=None)
        plans=ContextVar("shopping_plans",default=None)
        tool_plans=ContextVar("tool_plans",default=None)
        original_send = httpx.AsyncClient.send
        async def observed_send(self, request, *args, **kwargs):
            current = calls.get()
            catalog = reads.get()
            event=None
            if catalog is not None and request.url.port == 19834:
                catalog.append({"method":request.method,"path":request.url.path,"query":dict(request.url.params),
                    "body":json.loads(request.content) if request.content else None})
            if current is not None and request.url.host == "api.openai.com":
                body = json.loads(request.content)
                event={"at":datetime.now(timezone.utc).isoformat(),"mode":"live", "method":"HTTP", "path":request.url.path, "model":body.get("model"),"status":None}
                current.append(event)
                with open(OUT/"question-scope-answer-model-events.jsonl","a",encoding="utf-8") as f: f.write(json.dumps({**event,"event":"start"})+"\n")
            response=await original_send(self, request, *args, **kwargs)
            if event is not None:
                event["status"]=response.status_code
                event["completedAt"]=datetime.now(timezone.utc).isoformat()
                with open(OUT/"question-scope-answer-model-events.jsonl","a",encoding="utf-8") as f: f.write(json.dumps({**event,"event":"end"})+"\n")
            return response
        httpx.AsyncClient.send = observed_send
        original_complete=LlmClient.complete
        original_model=LlmClient.complete_with_tools
        original_answer=ChatService.answer
        async def complete(self,*args,**kwargs):
            result=await original_complete(self,*args,**kwargs)
            if plans.get() is not None:
                try: parsed=json.loads(result)
                except (ValueError,TypeError): parsed={"format":"text","length":len(result)}
                plans.get().append(parsed)
            return result
        async def model(self,*args,**kwargs):
            result=await original_model(self,*args,**kwargs)
            if tool_plans.get() is not None:
                for choice in result[0].get('choices',[]):
                    for call in choice.get('message',{}).get('tool_calls',[]):
                        function=call.get('function',{})
                        try: arguments=json.loads(function.get('arguments','{}'))
                        except ValueError: arguments={'format':'invalid_json'}
                        tool_plans.get().append({'tool':function.get('name'),'arguments':arguments})
            return result
        async def answer(self,req,*args,**kwargs):
            token=calls.set([])
            read_token=reads.set([])
            plan_token=plans.set([])
            tool_token=tool_plans.set([])
            started=datetime.now(timezone.utc).isoformat()
            try:
                response=await original_answer(self,req,*args,**kwargs)
                # No auth headers, account identifiers, passwords, or persisted memory text.
                record={"at":datetime.now(timezone.utc).isoformat(),"utterance":req.message,
                        "startedAt":started,"sourceSnapshot":source_snapshot.name,
                        "catalogCalls":reads.get(),
                        "shoppingPlans":plans.get(),
                        "toolPlans":tool_plans.get(),
                        "answer":response.answer,"modelCalls":calls.get(),
                        "requestType":req.request_type, "hasStyleContext":req.style_context is not None,
                        "hasG7Execution":req._g7_execution is not None,
                        "consultation":response.consultation.model_dump(mode="json",by_alias=True) if response.consultation else None, "sessionStatus":response.session_status,
                        "styleStatus":response.style_status,
                        "styleCandidates":[c.model_dump(mode="json",by_alias=True) for c in response.style_candidates or []],
                        "ownedLookContext":response._owned_look_context.model_dump(mode="json",by_alias=True) if response._owned_look_context else None,
                        "parent":response._consultation_parent.model_dump(mode="json",by_alias=True) if response._consultation_parent else None,
                        "tasks":response._parent_trace,
                        "products":[p.model_dump(mode="json",by_alias=True) for p in response.products],
                        "options":response.owned_look_options.model_dump(mode="json",by_alias=True) if response.owned_look_options else None}
                with open(OUT/"question-scope-answer-app-turns.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps(record,ensure_ascii=False)+"\n")
                return response
            except Exception as exc:
                with open(OUT/"question-scope-answer-app-turns.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"startedAt":started,"sourceSnapshot":source_snapshot.name,"utterance":req.message,"modelCalls":calls.get(),"catalogCalls":reads.get(),"errorCode":getattr(exc,"code",type(exc).__name__)},ensure_ascii=False)+"\n")
                raise
            finally:
                calls.reset(token)
                reads.reset(read_token)
                plans.reset(plan_token)
                tool_plans.reset(tool_token)
        LlmClient.complete=complete
        LlmClient.complete_with_tools=model
        ChatService.answer=answer
    app = create_app()
    if role == "chat":
        import time
        @app.middleware("http")
        async def observe_read(request, call_next):
            tracked = request.url.path.startswith("/api/chat")
            started = time.monotonic()
            if tracked:
                with open(OUT/"question-scope-answer-app-restore-http.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"event":"start","segments":len(request.url.path.split('/')),"method":request.method,"cancel":request.url.path.endswith("/cancel")})+"\n")
            response = await call_next(request)
            if tracked:
                with open(OUT/"question-scope-answer-app-restore-http.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"event":"end","status":response.status_code,"cancel":request.url.path.endswith("/cancel"),"ms":round((time.monotonic()-started)*1000,1)})+"\n")
            return response
    uvicorn.run(app,host="127.0.0.1",port=PORTS[role],access_log=False,log_level="warning")

if __name__=="__main__":
    if len(sys.argv)>1:
        serve(sys.argv[1])
    else:
        env=environment()
        log=open(OUT/"question-scope-answer-app-chat.log","ab")
        proc=subprocess.Popen([str(ROOT/"backend/chatbot/.venv/Scripts/python.exe"),"-B",str(Path(__file__).resolve()),"chat"],cwd=ROOT/"backend/chatbot",env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        (OUT/"question-scope-answer-app-runtime.json").write_text(json.dumps({"chatPid":proc.pid,"chatPort":19833,"model":env["LLM_MODEL"],"modelConfiguredMode":"live","startedAt":datetime.now(timezone.utc).isoformat()},indent=2),encoding="utf-8")
        print("Started current common answer local validation chat",proc.pid)



