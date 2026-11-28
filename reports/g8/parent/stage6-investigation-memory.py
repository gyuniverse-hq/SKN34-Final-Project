"""Temporary actual-PG flag probes; existing fixture, mock auth/model only."""
from uuid import uuid4
import pytest
from app.core.config import get_settings
from app.schemas.chat import ChatResponse
from app.services.chat_service import get_chat_service
from tests.test_g7_memory_api_pg import AUTH, ask, new_room

pytest_plugins=['tests.conftest','tests.test_g7_memory_api_pg']

def test_g7_persistence_off_keeps_ordinary_chat_but_blocks_saved_chat(memory_api,monkeypatch,record_property):
    client,chat=memory_api;room=new_room(client)
    monkeypatch.setattr(get_settings(),'g7_persistence_enabled',False)
    plain=client.post('/api/chat',headers=AUTH,json={'message':'ordinary synthetic question','locale':'ko'})
    assert plain.status_code==200 and plain.json()['answer']=='answer'
    saved=client.get(f'/api/chat/conversations/{room}',headers=AUTH)
    assert saved.status_code==503 and saved.json()['code']=='persistence_disabled'
    record_property('mode','actual PG fixture; mock auth/model; G7 persistence OFF ordinary200/saved503')

def test_global_memory_off_blocks_reads_writes_and_application(memory_api,monkeypatch,record_property):
    client,chat=memory_api;room=new_room(client)
    monkeypatch.setattr(get_settings(),'g7_memory_enabled',False)
    off=ask(client,room,0,'기억 반영해서 상품 추천',structured=True)
    assert chat.calls[-1]['memories']==[] and not off.get('appliedMemories')
    denied=client.post('/api/chat/memories',headers=AUTH,json={'requestId':str(uuid4()),'proposalId':str(uuid4()),'expectedProposalVersion':1,'confirmed':True})
    assert denied.status_code==503 and denied.json()['code']=='memory_unavailable'
    assert client.get('/api/chat/memories',headers=AUTH).status_code==503
    record_property('mode','actual PG; mock auth/model; global memory OFF; no applied memory and REST reads/writes503')

def test_structured_off_does_not_pass_inventory_or_create_groups(memory_api,monkeypatch,record_property):
    client,_=memory_api;room=new_room(client);seen=[]
    class Inspect:
        async def answer(self,req,principal):
            seen.append(req._consultation_memories)
            return ChatResponse(answer='synthetic',products=[])
    client.app.dependency_overrides[get_chat_service]=lambda:Inspect()
    monkeypatch.setattr(get_settings(),'g7_structured_memory_enabled',False)
    ask(client,room,0,'기존 상품을 추천해줘',structured=True)
    assert not seen[-1]
    monkeypatch.setattr(get_settings(),'g7_structured_memory_enabled',True)
    assert client.get('/api/chat/v2/memory-proposals',headers=AUTH,params={'conversationId':room}).json()==[]
    record_property('mode','actual PG; mock auth/model; structured flag OFF suppresses inventory and structured proposals')

def test_global_memory_switch_during_turn_blocks_late_commit(memory_api,monkeypatch,record_property):
    client,_=memory_api;room=new_room(client)
    class SwitchOff:
        async def answer(self,req,principal):
            monkeypatch.setattr(get_settings(),'g7_memory_enabled',False)
            return ChatResponse(answer='must not commit',products=[])
    client.app.dependency_overrides[get_chat_service]=lambda:SwitchOff()
    reply=client.post('/api/chat',headers=AUTH,json={'conversationId':room,'requestId':str(uuid4()),'expectedConversationVersion':0,'message':'synthetic in-flight flag change','locale':'ko'})
    assert reply.status_code==409 and reply.json()['code']=='request_interrupted'
    assert client.get(f'/api/chat/conversations/{room}',headers=AUTH).json()['messages']==[]
    record_property('mode','actual PG; controlled model; global memory disabled in-flight causes409 and no saved messages')
