"""Investigation launch/HTTP collector; immutable product files; model egress blocked."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
P='stage6-investigation-'

def environment():
    spec=importlib.util.spec_from_file_location('prior_runtime',OUT/'stage6-remediation-runtime.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    env=m.environment()
    env.update(PYTHONDONTWRITEBYTECODE='1',SKINCARE_REFRESH_ENABLED='false')
    return env

def event(name, value):
    with (OUT/(P+name+'.jsonl')).open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),**value},ensure_ascii=False)+'\n')

def route(path):
    if re.fullmatch(r'/api/chat/conversations/[^/]+/requests/[^/]+',path):return 'request-status'
    if re.fullmatch(r'/api/chat/conversations/[^/]+',path):return 'conversation-detail'
    if path=='/api/chat/conversations':return 'conversation-list'
    if path=='/api/chat':return 'chat'
    if path.startswith('/api/chat/v2/'):return 'structured-memory-'+path.split('/')[4]
    return 'other-chat' if path.startswith('/api/chat') else 'other'

def serve(role):
    sys.path.insert(0,str(ROOT/'backend'/('chatbot' if role=='chat' else 'api')))
    import uvicorn
    from app.main import create_app
    app=create_app()
    if role=='chat':
        from fastapi import Request
        from app.clients.llm_client import LlmClient
        from app.core.errors import ApiError
        import httpx
        async def blocked(*a,**k):
            event('blocked-models',{'kind':'LlmClient','mode':'blocked before external send'})
            raise ApiError(503,'Investigation model call blocked','investigation_model_blocked')
        LlmClient.complete=blocked
        LlmClient.complete_with_tools=blocked
        send=httpx.AsyncClient.send
        async def checked_send(self,request,*a,**k):
            if request.url.host=='api.openai.com':
                event('blocked-models',{'kind':'HTTP','mode':'blocked before external send'})
                raise RuntimeError('Investigation model egress blocked')
            return await send(self,request,*a,**k)
        httpx.AsyncClient.send=checked_send
        @app.post('/__g8_probe')
        async def probe(req:Request):
            value=await req.json()
            allowed={'at','phase','span','parent','route','method','status','mode','reading','current','selected','opened','alreadyOpening','automatic','retry','state','listLoading','listError','detailLoading','detailError','cursor'}
            assert set(value)<=allowed
            # Cursor values are never needed; only whether pagination exists.
            if 'cursor' in value:value['cursor']=value['cursor'] is not None
            assert len(json.dumps(value))<1500
            event('browser-events',value)
            return {'ok':True}
        @app.middleware('http')
        async def record_http(request,call_next):
            kind=route(request.url.path)
            if not request.url.path.startswith('/api/chat'):return await call_next(request)
            start=time.monotonic()
            info={'event':'start','route':kind,'method':request.method}
            if request.url.path=='/api/chat' and request.method=='POST':
                body=await request.json()
                info.update(messageSha256=hashlib.sha256(str(body.get('message','')).encode()).hexdigest(),requestIdSha256=hashlib.sha256(str(body.get('requestId','')).encode()).hexdigest())
            event('http',info)
            response=await call_next(request)
            event('http',{'event':'end','route':kind,'method':request.method,'status':response.status_code,'ms':round((time.monotonic()-start)*1000,2)})
            return response
    uvicorn.run(app,host='127.0.0.1',port=19833 if role=='chat' else 19834,access_log=False,log_level='warning')

def start(web_only=False,plain=False):
    env=environment();pids={};reused=[]
    for role,port in ([] if web_only else [('api',19834),('chat',19833)]):
        with socket.socket() as s: opened=s.connect_ex(('127.0.0.1',port))==0
        if opened:
            assert role=='api','Existing chat left untouched'
            reused.append(role);continue
        directory=ROOT/'backend'/('chatbot' if role=='chat' else 'api')
        cmd=['uv','run','--frozen','--no-sync','python','-u','-B',str(Path(__file__).resolve()),role]
        with (OUT/(P+role+'.log')).open('ab') as log:
            pids[role]=subprocess.Popen(cmd,cwd=directory,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW).pid
    web=dict(os.environ,CI='1',EXPO_NO_TELEMETRY='1',EXPO_PUBLIC_API_BASE_URL='http://localhost:19834',EXPO_PUBLIC_CHAT_API_BASE_URL='http://localhost:19833',EXPO_PUBLIC_SUPABASE_URL=env['SUPABASE_URL'],EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env['SUPABASE_PUBLISHABLE_KEY'])
    if not plain:web['NODE_OPTIONS']='--require='+str(OUT/(P+'metro-preload.cjs'))
    with (OUT/(P+'web.log')).open('ab') as log:
        pids['web']=subprocess.Popen(['node','node_modules/expo/bin/cli','start','--web','--port','19836','--localhost','--clear'],cwd=ROOT,env=web,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW).pid
    if web_only:
        old=json.loads((OUT/(P+'runtime.json')).read_text());pids={**old['pids'],**pids}
    (OUT/(P+'runtime.json')).write_text(json.dumps({'pids':pids,'reused':reused,'ports':{'chat':19833,'catalog':19834,'web':19836},'model':'blocked in this restore-only runtime','auth':'real Supabase session','chatDatabase':'vishue_g8_browser','instrumentation':'none in plain web' if plain else 'memory-only Metro transformation; product/config bytes unchanged'},indent=2),encoding='utf-8')
    print('Started investigation runtime',pids,'reused',reused,flush=True)

if __name__=='__main__':
    if '--web-only' in sys.argv:start(web_only=True,plain='--plain' in sys.argv)
    elif len(sys.argv)>1:serve(sys.argv[1])
    else:start()
