"""Read synthetic app sessions only; never export owner IDs or credentials."""
import importlib.util,json,sys
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from sqlalchemy.engine import make_url
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'backend/chatbot'))
from app.schemas.catalog import OptionSearchResponse
s=importlib.util.spec_from_file_location('r',HERE/'completion-restore-app-run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
u=make_url(m.environment()['CHAT_DATABASE_URL']).set(drivername='postgresql');assert u.database=='vishue_g8_browser'
records=[]
with psycopg.connect(u.render_as_string(hide_password=False)) as c:
 c.execute('SET TRANSACTION READ ONLY')
 for utterance in ['토너 찾아줘. 크림도 찾아줘','2만원 이하 립 상품 판매 옵션 찾아줘. 3만원 이하 베이스 상품 판매 옵션도 찾아줘']:
  row=c.execute("SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s AND created_at>%s ORDER BY created_at DESC LIMIT 1",(utterance,'2026-11-27T15:59:00Z')).fetchone();assert row
  cid=row[0]
  msgs=c.execute('SELECT role,text,display_payload FROM chat_messages WHERE conversation_id=%s ORDER BY sequence',(cid,)).fetchall()
  ctx=c.execute('SELECT context_json FROM chat_conversations WHERE id=%s',(cid,)).fetchone()[0]
  p=ctx['consultationParent'];summary=msgs[-1][2]['consultation']
  assert len(p['tasks'])==2
  if utterance.startswith('토너'):
   assert summary['status']=='completed'
  else:
   assert summary['status']=='partial' and len(summary['displayChoices'])==2
   chosen=summary['selectedTaskId'];task=next(t for t in p['tasks'] if t['taskId']==chosen)
   assert p['resultSelection']['selectedTaskId']==chosen
   assert OptionSearchResponse.model_validate(task['displayResult']['optionSearch'])==OptionSearchResponse.model_validate(msgs[-1][2]['optionSearch'])
   assert sorted(t['productContext']['filters']['maxPriceKRW'] for t in p['tasks'])==[20000,30000]
  records.append({'utterance':utterance,'summary':summary,'parent':p,'selectedProduct':ctx.get('product'),
   'messages':[{'role':r[0],'text':r[1],'displayPayload':r[2]} for r in msgs]})
(HERE/'completion-restore-app-pg.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'mode':'actual PG/login app','result':'PASS','sessions':records},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS two actual app sessions; summary/choice/query scope/budgets persisted; option result exact')

