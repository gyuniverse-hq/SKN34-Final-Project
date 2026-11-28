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
        log=open(OUT/f"common-answer-app-{role}.log","ab")
        proc=subprocess.Popen([str(python),"-B",str(Path(__file__).resolve()),role],cwd=directory,env=env,
                              stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        processes[role]=proc.pid
    web=dict(os.environ,PYTHONUTF8="1",CI="1",EXPO_NO_TELEMETRY="1",
             EXPO_PUBLIC_API_BASE_URL="http://localhost:19834",
             EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833",
             EXPO_PUBLIC_SUPABASE_URL=env["SUPABASE_URL"],
             EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env["SUPABASE_PUBLISHABLE_KEY"])
    log=open(OUT/"common-answer-app-web.log","ab")
    proc=subprocess.Popen(["node","node_modules/expo/bin/cli","start","--web","--port","19836","--localhost"],
                          cwd=ROOT,env=web,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    processes["web"]=proc.pid
    (OUT/"common-answer-app-runtime.json").write_text(json.dumps({"ports":PORTS,"pids":processes,"chatDatabase":DB,
        "auth":"real_supabase", "model":env["LLM_MODEL"],"g5Enabled":False,
        "startedAt":datetime.now(timezone.utc).isoformat()},indent=2),encoding="utf-8")
    print("Started isolated runtime",processes,flush=True)

def serve(role):
    directory=ROOT/"backend"/("chatbot" if role=="chat" else "api")
    sys.path.insert(0,str(directory))
    import uvicorn
    from app.main import create_app
    if role=="chat":
        from app.clients.llm_client import LlmClient
        from app.services.chat_service import ChatService
        calls=ContextVar("e2e_calls",default=None)
        original_complete=LlmClient.complete
        original_model=LlmClient.complete_with_tools
        original_answer=ChatService.answer
        async def complete(self,*args,**kwargs):
            current=calls.get()
            if current is not None: current.append({"mode":"live", "method":"complete"})
            return await original_complete(self,*args,**kwargs)
        async def model(self,*args,**kwargs):
            current=calls.get()
            if current is not None: current.append({"mode":"live", "method":"complete_with_tools"})
            return await original_model(self,*args,**kwargs)
        async def answer(self,req,*args,**kwargs):
            token=calls.set([])
            try:
                response=await original_answer(self,req,*args,**kwargs)
                # No auth headers, account identifiers, passwords, or persisted memory text.
                record={"at":datetime.now(timezone.utc).isoformat(),"utterance":req.message,
                        "answer":response.answer,"modelCalls":calls.get(),
                        "requestType":req.request_type, "hasStyleContext":req.style_context is not None,
                        "hasG7Execution":req._g7_execution is not None,
                        "sessionStatus":response.session_status,
                        "styleStatus":response.style_status,
                        "styleCandidates":[c.model_dump(mode="json",by_alias=True) for c in response.style_candidates or []],
                        "ownedLookContext":response._owned_look_context.model_dump(mode="json",by_alias=True) if response._owned_look_context else None,
                        "parent":response._consultation_parent.model_dump(mode="json",by_alias=True) if response._consultation_parent else None,
                        "tasks":response._parent_trace,
                        "products":[p.model_dump(mode="json",by_alias=True) for p in response.products],
                        "options":response.owned_look_options.model_dump(mode="json",by_alias=True) if response.owned_look_options else None}
                with open(OUT/"common-answer-app-turns.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps(record,ensure_ascii=False)+"\n")
                return response
            finally: calls.reset(token)
        LlmClient.complete=complete
        LlmClient.complete_with_tools=model
        ChatService.answer=answer
    app = create_app()
    if role == "chat":
        import time
        @app.middleware("http")
        async def observe_read(request, call_next):
            tracked = request.method == "GET" and request.url.path.startswith("/api/chat/conversations")
            started = time.monotonic()
            if tracked:
                with open(OUT/"common-answer-app-restore-http.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"event":"start","segments":len(request.url.path.split('/'))})+"\n")
            response = await call_next(request)
            if tracked:
                with open(OUT/"common-answer-app-restore-http.jsonl","a",encoding="utf-8") as f:
                    f.write(json.dumps({"at":datetime.now(timezone.utc).isoformat(),"event":"end","status":response.status_code,"ms":round((time.monotonic()-started)*1000,1)})+"\n")
            return response
    uvicorn.run(app,host="127.0.0.1",port=PORTS[role],access_log=False,log_level="warning")

if __name__=="__main__":
    if len(sys.argv)>1:
        serve(sys.argv[1])
    else:
        env=environment()
        log=open(OUT/"common-answer-app-chat.log","ab")
        proc=subprocess.Popen([str(ROOT/"backend/chatbot/.venv/Scripts/python.exe"),"-B",str(Path(__file__).resolve()),"chat"],cwd=ROOT/"backend/chatbot",env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        (OUT/"common-answer-app-runtime.json").write_text(json.dumps({"chatPid":proc.pid,"chatPort":19833,"model":env["LLM_MODEL"],"modelConfiguredMode":"live","startedAt":datetime.now(timezone.utc).isoformat()},indent=2),encoding="utf-8")
        print("Started current common answer local validation chat",proc.pid)
