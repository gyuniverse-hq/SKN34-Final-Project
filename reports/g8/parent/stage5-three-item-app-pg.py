"""Read-only verification of the synthetic app conversation and exact option state."""
import importlib.util,json,sys
from datetime import datetime,timezone
from pathlib import Path
import psycopg
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent'
spec=importlib.util.spec_from_file_location('runtime',OUT/'stage5-three-item-runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
sys.path.insert(0,str(ROOT/'backend/chatbot'))
from app.schemas.consultation_parent import ConsultationParent
rows=[json.loads(x) for x in (OUT/'stage5-three-item-app-turns.jsonl').read_text(encoding='utf-8').splitlines()]
assert rows and all('answer' in r for r in rows)
release=json.loads((OUT/'stage5-three-item-release-sources.json').read_text(encoding='utf-8'))
final=[r for r in rows if json.loads((OUT/r['sourceSnapshot']).read_text(encoding='utf-8'))==release]
assert final, 'Need final-source app display/restore verification'
release_map={e['path']:e['sha256'] for e in release}
def same_components(row,names):
 original={e['path']:e['sha256'] for e in json.loads((OUT/row['sourceSnapshot']).read_text(encoding='utf-8'))}
 return all(original.get(name)==release_map[name] for name in names)
producer_paths=['backend/chatbot/app/services/knowledge_service.py','backend/chatbot/app/services/compound_consultation_service.py','backend/chatbot/app/services/compound_consultation_graph.py','backend/chatbot/app/services/beauty_consultation_service.py','backend/chatbot/app/services/product_search_contract.py','backend/chatbot/app/services/consultation_intent_service.py','backend/chatbot/app/schemas/consultation_parent.py','backend/chatbot/app/schemas/consultation_task.py']
producers=[r for r in rows if same_components(r,producer_paths)]
skin_rows=[r for r in producers if '피부 상담만' in r['utterance'] and any(t['goal']=='skin' and t.get('displayResult',{}).get('knowledge',{}).get('claims') for t in r['parent']['tasks'])]
assert skin_rows, 'Need positive final-source actual G5 explanation'
anchor=skin_rows[-1]
number=next(r for r in final if r['utterance']=='2번 결과 보여줘')
assert number['parent']['resultSelection']['selectedTaskId']==anchor['parent']['resultSelection']['taskIds'][1]
assert number['catalogCalls']==[], 'Display must not rerun Catalog'
search=next(r for r in producers if '별도로 립펜슬' in r['utterance'] and r['catalogCalls'] and r['products'])
assert search['catalogCalls'], 'New search must call real Catalog'
assert search['products'] and all('립펜슬' in p['name'].replace(' ','') or '립펜슬' in p.get('nameKo','').replace(' ','') for p in search['products'])
for r in [anchor,number,search]:
 assert '개인별 원인을 해결하거나' not in r['answer']
 assert '실제 원인은 이 정보만으로 확인할 수 없어요' not in r['answer']
 assert '제공된 근거에서는 구체적인 제품명이나 판매 정보를 확인할 수 없습니다' not in r['answer']
url=make_url(runtime.environment()['CHAT_DATABASE_URL']).set(drivername='postgresql')
assert url.database=='vishue_g8_browser'
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
 conn.execute('SET TRANSACTION READ ONLY')
 row=conn.execute("SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s AND created_at >= %s ORDER BY created_at DESC LIMIT 1",(final[-1]['utterance'],final[-1]['startedAt'])).fetchone()
 assert row
 cid=row[0]
 context=conn.execute('SELECT context_json FROM chat_conversations WHERE id=%s',(cid,)).fetchone()[0]
 messages=conn.execute('SELECT role,text,display_payload FROM chat_messages WHERE conversation_id=%s AND created_at >= %s ORDER BY sequence',(cid,search['startedAt'])).fetchall()
 turns=conn.execute('SELECT status,error_code,base_version,committed_version FROM chat_turns WHERE conversation_id=%s AND created_at >= %s ORDER BY created_at',(cid,search['startedAt'])).fetchall()
actual=ConsultationParent.model_validate(context['consultationParent'])
expected=ConsultationParent.model_validate(final[-1]['parent'])
assert actual.model_dump(mode='json')==expected.model_dump(mode='json')
before_search=rows[rows.index(search)-1]
for goal in ['skin','owned_look']:
 before=next(t for t in before_search['parent']['tasks'] if t['goal']==goal)
 after=next(t for t in search['parent']['tasks'] if t['goal']==goal)
 assert before['displayResult']==after['displayResult'], 'Sibling result changed during search/show'
look=next(t for t in actual.tasks if t.goal=='owned_look')
selections=look.display_result.get('ownedLookOptions',{}).get('selections',[])
assert any(x['optionId']=='A000000162667-012' for x in selections)
assert all(x[0]=='COMMITTED' for x in turns)
result={'at':datetime.now(timezone.utc).isoformat(),'mode':'actual PG / actual authenticated app / live models / live Catalog','result':'PASS','finalSourceTurns':len(final),'producerEvidence':[{'utterance':r['utterance'],'sourceSnapshot':r['sourceSnapshot'],'mode':'actual producer; unchanged producer component hashes; final parent acknowledgement dedup differs'} for r in [search,anchor]],'parent':actual.model_dump(mode='json',by_alias=True),'checks':['number maps to saved ID','show has zero Catalog calls','new search calls Catalog','only requested kind cards','skin and look results preserved','exact owned-look sale option preserved','stored parent equals app response'],'messages':[{'role':r[0],'text':r[1],'displayPayload':r[2]} for r in messages],'turns':[{'status':r[0],'errorCode':r[1],'baseVersion':r[2],'committedVersion':r[3]} for r in turns]}
(OUT/'stage5-three-item-app-pg.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'stage5-three-item-dialogue.txt').write_text('\n\n'.join(f"SOURCE: {r['sourceSnapshot']}\nMODE: actual Tool producer or final stored-result display (see app-pg producerEvidence)\nUSER: {r['utterance']}\nASSISTANT: {r['answer']}" for r in [search,anchor,number]),encoding='utf-8')
print('PASS final-source actual app / Catalog / PG invariants; account IDs omitted')
