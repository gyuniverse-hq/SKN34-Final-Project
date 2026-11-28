"""Preserve this approved verification, without credentials."""
import hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
PREFIX='integration-n01-resolution'
old=json.loads((OUT/'common-price-followup-record.json').read_text(encoding='utf-8'))
paths={x['path'] for x in old['sourceSha256']}
paths.update(['backend/chatbot/app/schemas/compound_consultation.py','backend/chatbot/app/services/compound_consultation_service.py','backend/chatbot/app/services/compound_consultation_graph.py','backend/chatbot/tests/test_g8_compound_consultation.py','backend/chatbot/tests/test_g7_memory_api_pg.py','__tests__/useChatConversations.test.tsx'])
paths=sorted(p for p in paths if (ROOT/p).is_file())
(OUT/f'{PREFIX}-source.diff').write_bytes(subprocess.check_output(['git','diff','--binary','HEAD','--',*paths],cwd=ROOT))
untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
(OUT/f'{PREFIX}-new-sources.json').write_text(json.dumps([{'path':p,'content':(ROOT/p).read_text(encoding='utf-8')} for p in paths if p in untracked],ensure_ascii=False,indent=2),encoding='utf-8')
record={'case':'G8-N01-RESOLUTION-APP-RESTORE-20261127','at':datetime.now(timezone.utc).isoformat(),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),'uncommitted':True,'stage':'5 cooperation; 6 partial verification; G8 incomplete','sourceSha256':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths],'sourceDiff':f'reports/g8/parent/{PREFIX}-source.diff','untrackedSources':f'reports/g8/parent/{PREFIX}-new-sources.json','tests':[{'path':f.relative_to(ROOT).as_posix(),**ET.parse(f).getroot().find('testsuite').attrib} for f in sorted(OUT.glob(f'{PREFIX}-*.xml'))],'static':{'ruff':'PASS','importLinter':'3 KEPT','typecheck':'PASS','lint':'PASS'},'appMock':{'suites':2,'passed':39},'models':{'configuredMode':'live','planner':'gpt-6-luna','g5':'gpt-6.1-terra','failedLivePg':[1,5],'passedLivePg':[1,6],'g5ReplayPg':[1,3,2],'loginApp':[1,6],'observedRemoteHttpTotal':26,'apiInternalEmbedding':'not instrumented'},'n01':{'catalog':'live','pg':'live','pgAuth':'mock','appAuth':'live','fallback':'PASS with G5 replay plus live extraction/Catalog/PG; mock branch PASS','allLive':'PASS explanation and query; PARTIAL 6 excluded/4 unknown; no eligible option','dataVersion':'local-20261104-conservative-v1-20261123T111457291156Z'},'restore':{'finalSource':'PASS N01 and N02 stored conversation; Enter keyboard activation','saleDetail':'PASS A000000162667-012; exact option preserved; payment restricted','diagnosis':'pointer automation did not invoke selection; background refresh GET200 is not proof of selection; no auth defect established','productAppChanges':'diagnostic instrumentation removed','mobileTouch':'NOT_RUN'},'security':'Gitleaks8.30.1 empty-ignore before append','cleanup':'API19838 and relay19841 closed; Catalog/PG preserved','remaining':['all-live fallback positive data','pointer/mobile touch','all scenarios login-app E2E','device AR','human review'],'commitPushPr':'NOT_RUN'}
(OUT/f'{PREFIX}-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Preserved',len(paths),'sources')
