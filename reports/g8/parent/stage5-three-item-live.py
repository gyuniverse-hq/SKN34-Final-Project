"""Nine fixed synthetic interpretations with live parent and specialist models."""
import asyncio, hashlib, importlib.util, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
spec=importlib.util.spec_from_file_location('runtime',OUT/'stage5-three-item-runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
env=runtime.environment();os.environ.update(env)
sys.path.insert(0,str(ROOT/'backend/chatbot'))
from app.clients.llm_client import LlmClient
from app.schemas.chat import ChatRequest
from app.schemas.consultation_parent import ConsultationParent, ParentQuestion, ParentTask, ResultSelection
from app.services.consultation_intent_service import prepare_turn
from app.services.beauty_consultation_service import interpret_beauty
from app.services.product_search_contract import resolve_requirement
import httpx
EVENTS=[]
PROPOSALS=[]
original_send=httpx.AsyncClient.send
async def observed(self,request,*args,**kwargs):
    if request.url.host!='api.openai.com':return await original_send(self,request,*args,**kwargs)
    body=json.loads(request.content)
    event={'at':datetime.now(timezone.utc).isoformat(),'model':body.get('model'),'configuredMode':'live','path':request.url.path,'status':None}
    EVENTS.append(event)
    response=await original_send(self,request,*args,**kwargs)
    event['status']=response.status_code
    content=response.json()
    PROPOSALS.append(content.get('choices',[{}])[0].get('message',{}))
    return response
httpx.AsyncClient.send=observed

def request(message,reverse=False):
    req=ChatRequest(message=message,locale='ko')
    parent=ConsultationParent(tasks=[
        ParentTask(task_id='task-skin',goal='skin',version=1,status='partial',objective='오후에 화장이 뜨는 원인과 상품 추천'),
        ParentTask(task_id='task-look',goal='owned_look',version=1,status='partial',objective='보유 제품 기준 룩 상담'),
        ParentTask(task_id='task-product',goal='product',product_operation='search',version=1,status='waiting_user',objective='립펜슬 찾아줘.')])
    parent.pending_questions=[ParentQuestion(task_id='task-product',goal='product',version=1,text='찾으시는 상품 종류를 확인해 주세요.',input_key='selection')]
    parent.question=parent.pending_questions[0]
    parent.result_selection=ResultSelection(version=1,task_ids=['task-look','task-skin'] if reverse else ['task-skin','task-look'])
    req._consultation_parent=parent
    return req

async def main():
    model=LlmClient(env['LLM_BASE_URL'],env['LLM_API_KEY'],env['LLM_MODEL'],60)
    rows=[]
    for repeat in range(1,4):
        for case,message,reverse,expected in [
            ('number','2번 결과 보여줘',False,'task-look'),
            ('reordered','1번 결과 보여줘',True,'task-look'),
            ('new_search','별도로 립펜슬 찾아줘. 피부 상담과 룩 상담 결과는 그대로 유지해줘.',False,None)]:
            if '--new-only' in sys.argv and case!='new_search':continue
            req=request(message,reverse);start=len(EVENTS);proposal_start=len(PROPOSALS)
            response=await prepare_turn(req,model)
            intent=req._parent_intent
            ok=bool(intent)
            record={'repeat':repeat,'case':case,'utterance':message,'modelConfiguredMode':'live','response':response.answer if response else None,'intent':intent.model_dump(mode='json',by_alias=True) if intent else None}
            if expected:
                ok=ok and intent.action=='show' and intent.targets==[expected] and len(req._consultation_parent.pending_questions)==1
            else:
                reads=[c for c in intent.changes if c.task_id=='task-product' and c.operation=='update'] if intent else []
                additions=[a for a in intent.additions if a.capability=='product'] if intent else []
                candidates=reads+additions
                ok=ok and intent.action=='continue' and len(candidates)==1 and candidates[0].product_operation=='search'
                if ok:
                    child=ChatRequest(message=candidates[0].quote,locale='ko')
                    child._product_contract_required=True;child._product_operation='search'
                    plan=await interpret_beauty(child,model)
                    requirement,unresolved=resolve_requirement(None,plan.product_requirement,child.message,required=True)
                    record['shoppingPlan']=plan.model_dump(mode='json',by_alias=True)
                    record['requirement']=requirement.model_dump(mode='json')
                    ok=plan.intent=='search' and plan.category=='lip' and requirement.name_term=='립펜슬' and not unresolved and not plan.unsupported_conditions
            record['intentAudit']=req._parent_intent_audit
            record['rawProposals']=PROPOSALS[proposal_start:]
            record['actualModelCalls']=len(EVENTS)-start;record['pass']=bool(ok);rows.append(record)
            (OUT/('stage5-three-item-live-debug.json' if '--new-only' in sys.argv else 'stage5-three-item-live.json')).write_text(json.dumps({'cases':rows,'events':EVENTS,'pass':all(x['pass'] for x in rows)},ensure_ascii=False,indent=2),encoding='utf-8')
            print(case,repeat,'PASS' if ok else 'FAIL','HTTP',len(EVENTS)-start,flush=True)
    assert all(x['pass'] for x in rows), 'Live contract failure; original outputs retained'

if __name__=='__main__':asyncio.run(main())
