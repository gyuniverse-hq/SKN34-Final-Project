"""Link current contracts to actual and historical evidence without upgrading old passes."""
import ast,hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent'
anchors=[('backend/chatbot/tests/test_g8_consultation_intent.py','test_first_entry_splits_same_role_without_seed'),('backend/chatbot/tests/test_g8_consultation_intent.py','test_first_entry_preserves_ready_work_and_question_owner'),('backend/chatbot/tests/test_g8_consultation_intent.py','test_restored_scope_selection_shows_only_chosen_result_without_specialist_calls'),('backend/chatbot/tests/test_g8_consultation_parent.py','test_common_completion_uses_all_active_goal_states'),('backend/chatbot/tests/test_g8_consultation_parent.py','test_multiple_scopes_do_not_overwrite_ownership_question_or_become_unfinished_work'),('backend/chatbot/tests/test_g7_conversation_api_pg.py','test_completion_restore_keeps_two_query_scopes_and_selected_result')]
for file,name in anchors:
 assert name in [n.name for n in ast.walk(ast.parse((ROOT/file).read_text(encoding='utf-8-sig'))) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
history=[]
for name in ['common-entry-cooperation','common-cooperation-followup','common-execution-control','common-execution-control-app']:
 p=OUT/(name+'-record.json');assert p.is_file();r=json.loads(p.read_text(encoding='utf-8-sig'))
 files=r.get('sourceSha256',[])
 if isinstance(files,dict): files=[{'path':k,'sha256':v}for k,v in files.items()]
 history.append({'record':p.relative_to(ROOT).as_posix(),'changedSourcePaths':[x['path']for x in files if not (ROOT/x['path']).is_file() or hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()!=x['sha256']], 'classification':'historical execution, not an exact current-source live pass'})
rows=[
 {'bundle':1,'current':'unit + actual initial two-product plans','evidence':['completion-restore-unit.xml','completion-restore-app-turns.jsonl'],'remaining':'holdout expressions and original N01 full live not rerun'},
 {'bundle':2,'current':'existing binding and domain contracts pass current regression','evidence':['completion-restore-backend.xml'],'historical':['common-entry-cooperation-record.json','common-cooperation-followup-record.json'],'remaining':'G5 cooperation not rerun live; general arbitrary bindings unsupported'},
 {'bundle':3,'current':'unit question identity + actual retry/preserve/show; real PG','evidence':['completion-restore-unit.xml','completion-restore-pg-regression.log','completion-restore-app-turns.jsonl'],'remaining':'multiple specialist questions together not run live; budget change not run live this time'},
 {'bundle':4,'current':'existing guards + current backend regression','evidence':['completion-restore-backend.xml'],'historical':['common-execution-control-record.json','common-execution-control-app-record.json'],'remaining':'latest summary + full cancel E2E not rerun; active HTTP force-stop not supported'},
 {'bundle':5,'current':'completion/partial classification; result scope selection; PG/app restore; exact unique option detail','evidence':['completion-restore-unit.xml','completion-restore-pg-final.log','completion-restore-app-pg.json','completion-restore-app-final-detail-loaded.txt','completion-restore-app-final2.log'],'remaining':'initial fragrance/kind failure not retested after environment correction; all-synthetic classification matrix not all live; native mobile not run'},
 {'bundle':6,'current':'source/evidence linkage; historical records preserved; security before append','evidence':['completion-restore-record.json','completion-restore-source.diff'],'remaining':'stage5 exit retained as incomplete; original14 capabilities/12 scenarios and N01/N02/E01/B01 full integration in stage6'}]
(OUT/'completion-restore-exit-matrix.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'stage5Exit':'INCOMPLETE','anchors':[{'path':p,'test':t}for p,t in anchors],'bundles':rows,'historicalSourceComparison':history},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS',len(anchors),'test anchors;',len(rows),'exit rows;',len(history),'historical manifests compared')
