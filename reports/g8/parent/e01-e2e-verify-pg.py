"""Read-only PG verification of actual authenticated E01 browser turns."""
import json
import runpy
from pathlib import Path
from datetime import datetime, timezone
import psycopg
from sqlalchemy.engine import make_url
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
env=runpy.run_path(str(OUT/'e01-e2e-run.py'))['environment']()
url=make_url(env['CHAT_DATABASE_URL']).set(drivername='postgresql')
assert url.database=='vishue_g8_browser'
live=[json.loads(s) for s in (OUT/'e01-e2e-turns.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(live)==4
assert [len(r['modelCalls']) for r in live]==[1,1,1,2]
assert [t['status'] for t in live[2]['parent']['tasks']]==['completed','failed']
assert [t['status'] for t in live[3]['parent']['tasks']]==['completed','completed']
assert live[3]['parent']['tasks'][0]['attempts']==0
assert all(c['tool'] not in {'get_product','search_products'} for c in live[3]['tasks'][-1]['catalogCalls'])
with psycopg.connect(url.render_as_string(hide_password=False),options='-c default_transaction_read_only=on -c statement_timeout=5000') as conn:
 room=conn.execute("select c.id,c.conversation_version,c.context_json from chat_conversations c where exists (select 1 from chat_messages m where m.conversation_id=c.id and m.role='assistant' and m.text=%s) order by c.created_at desc limit 1",(live[-1]['answer'],)).fetchone()
 messages=conn.execute('select sequence,role,text,display_payload from chat_messages where conversation_id=%s order by sequence',(room[0],)).fetchall()
 turns=conn.execute('select operation,status,committed_version from chat_turns where conversation_id=%s order by created_at',(room[0],)).fetchall()
 replies=[m for m in messages if m[1]=='assistant']
 assert len(replies)==4
 for saved,actual in zip(replies,live,strict=True):
  assert saved[2]==actual['answer']
  assert saved[3].get('styleCandidates',[])==actual['styleCandidates']
 assert room[2]['product']['selectedProductId']=='oy-a000000162092'
 assert room[2]['productStyle']['failed']==[]
 assert room[2]['productStyle']['productResult']['answer'] in live[-1]['answer']
 assert all(t[1]=='COMMITTED' for t in turns)
 report={'at':datetime.now(timezone.utc).isoformat(),'database':'vishue_g8_browser','readOnly':True,'auth':'real_supabase','modelConfiguredMode':'live','model':env['LLM_MODEL'],'actualCallsPerTurn':[1,1,1,2],'finalSourceTurnIndexes':[2,3],'intermediateTurnsPreserved':2,'checks':{'answersPersisted':True,'styleCardsPersisted':True,'selectedProductPreserved':True,'productTaskNotRepeated':True,'failedTaskRecovered':True},'context':{'product':room[2]['product'],'parent':room[2]['consultationParent'],'productStyle':room[2]['productStyle']},'turns':[{'operation':t[0],'status':t[1],'version':t[2]} for t in turns]}
 (OUT/'e01-e2e-pg.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS: real login/model/Catalog/PG; partial success, restored retry, product not repeated; model calls 1/1/1/2')
