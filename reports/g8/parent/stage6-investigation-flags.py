"""Real ChatService/planner graph; synthetic model/Catalog; no external HTTP."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend/chatbot'))
print('Importing current chatbot modules',flush=True)
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.chat import ChatRequest
from app.schemas.knowledge import KnowledgeReply
from app.services.chat_service import ChatService
from app.services.knowledge_service import Consultation
from app.services.conversation_context import prepare_request, updated_context
from app.services.conversation_service import require_persistence
from tests.conftest import FakeGraph
import httpx

class Planner:
    configured=True
    def __init__(self): self.calls=[]
    async def complete(self,messages):
        self.calls.append('legacy_complete')
        return 'Synthetic ordinary answer'
    async def complete_with_tools(self,messages,tools,*,required_tool=None):
        self.calls.append(required_tool)
        data=json.loads(messages[-1]['content'])
        args={'planId':data['planId'],'version':data['version'],'action':'continue'}
        if required_tool=='plan_consultation_entry':
            args['additions']=[{'capability':'knowledge','quote':data['utterance']}]
        else:
            args['changes']=[{'taskId':data['tasks'][0]['taskId'],'operation':'update','quote':data['utterance']}]
        return {'choices':[{'message':{'tool_calls':[{'function':{'name':required_tool,'arguments':json.dumps(args)}}]}}]},0

async def main():
    settings=get_settings(); results=[]; knowledge=[]; http=[]
    async def no_network(self,request,*a,**k):
        http.append(request.url.host)
        raise AssertionError('Unexpected HTTP; endpoint/value withheld')
    async def synthetic_knowledge(self,*a,**k):
        knowledge.append(True)
        return Consultation(KnowledgeReply(status='error',limitations='Synthetic boundary probe'),{})
    with patch.object(httpx.AsyncClient,'send',new=no_network), patch('app.services.knowledge_service.KnowledgeService.consult',new=synthetic_knowledge), patch.object(settings,'g1_supervisor_enabled',False), patch.object(settings,'g5_openai_api_key','synthetic-investigation-key'), patch.object(settings,'g5_internal_token','synthetic-investigation-token'):
        with patch.object(settings,'g8_enabled',True),patch.object(settings,'g5_enabled',False):
            model=Planner(); service=ChatService(FakeGraph(),model)
            first=await asyncio.wait_for(service.answer(ChatRequest(message='세안 후 보습 순서를 설명해줘',locale='ko')),10)
            results.append({'case':'G5_OFF_G8_entry','g1':False,'g5':False,'g8':True,'knowledgeAdapterCalls':len(knowledge),'mockModelCalls':model.calls.copy(),'finding':'G5 OFF bypass reproduced' if knowledge else 'blocked'})
            print('Completed G5 OFF entry',flush=True)
            context=updated_context({},first)
            # Serialize exactly as persistence would; restore through the real server adapter.
            restored=prepare_request(ChatRequest(message='그 설명을 다시 해줘',locale='ko'),json.loads(json.dumps(context)),[])
            before=len(knowledge); await asyncio.wait_for(service.answer(restored),10)
            results.append({'case':'G5_OFF_G8_restored_followup','knowledgeAdapterCalls':len(knowledge)-before,'finding':'G5 OFF bypass reproduced' if len(knowledge)>before else 'blocked'})
            print('Completed restored followup',flush=True)
        with patch.object(settings,'g8_enabled',False),patch.object(settings,'g5_enabled',False):
            model=Planner(); service=ChatService(FakeGraph(),model)
            await asyncio.wait_for(service.answer(ChatRequest(message='안녕',locale='ko')),10)
            results.append({'case':'G8_OFF_fresh','parentPlanningCalls':sum(x in ('plan_consultation_entry','interpret_consultation_change') for x in model.calls),'mockModelCalls':model.calls.copy()})
            old=prepare_request(ChatRequest(message='안녕',locale='ko'),json.loads(json.dumps(context)),[])
            before=len(knowledge); reply=await asyncio.wait_for(service.answer(old),10)
            results.append({'case':'G8_OFF_stored_active','knowledgeAdapterCalls':len(knowledge)-before,'answer':reply.answer,'parentReturned':reply._consultation_parent is not None})
            old._consultation_parent.execution_state='cancelled'
            reply=await asyncio.wait_for(service.answer(old),10)
            results.append({'case':'G8_OFF_stored_cancelled','answer':reply.answer,'parentReturned':reply._consultation_parent is not None,'classification':'observed compatibility behavior; policy decision before calling it a defect'})
        for enabled,env in [(False,'local'),(True,'local'),(True,'production')]:
            with patch.object(settings,'g7_persistence_enabled',enabled),patch.object(settings,'env',env),patch.object(settings,'chat_database_url','postgresql+psycopg://unused/unused'):
                try: require_persistence(); result='allowed'
                except ApiError as exc: result=exc.code
                results.append({'case':'G7_persistence_gate','enabled':enabled,'environment':env,'result':result})
    assert not http
    assert results[0]['knowledgeAdapterCalls']==1 and results[1]['knowledgeAdapterCalls']==1
    assert results[2]['parentPlanningCalls']==0
    path=ROOT/'reports/g8/parent/stage6-investigation-flags.json'
    path.write_text(json.dumps({'head':'200010e1','mode':'real current ChatService, graph and consult_knowledge wrapper; configured synthetic keys; only inner KnowledgeService.consult and model are mock; zero HTTP; assertions confirm observed defect, not desired behavior','results':results,'externalHTTP':len(http)},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False),flush=True)

if __name__=='__main__': asyncio.run(main())
