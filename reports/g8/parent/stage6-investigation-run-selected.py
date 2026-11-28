"""Reuse existing selected contracts with disposable actual PG; no live LLM flags."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent';P='stage6-investigation-'
spec=importlib.util.spec_from_file_location('runtime',OUT/(P+'runtime.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
env=m.environment()
from sqlalchemy.engine import make_url
url=make_url(env['CHAT_DATABASE_URL']).set(database='vishue_chat_test')
env.update(TEST_CHAT_DATABASE_URL=url.render_as_string(hide_password=False),CHAT_DATABASE_URL=url.render_as_string(hide_password=False))
assert url.database=='vishue_chat_test'
for flag in ('G8_N02_LIVE_CATALOG','G8_E01_LIVE_CATALOG','G8_EXECUTION_LIVE','G8_COMPARISON_SELECTION_LIVE','G8_CURRENT_PRICE_FOLLOWUP'):
    env.pop(flag,None)
select='consent_ownership_idempotency_and_redaction or memory_policy_and_catalog_application_end_to_end or memory_edit_invalidates_old_redis_candidates or structured_memory_partial_approval_preserves_versions_and_sources'
commands=[('memory-flags',[str(OUT/(P+'memory.py'))])] if '--memory-flags' in sys.argv else [('unit',['tests/test_g7_conversation_service.py','tests/test_g7_memory_service.py']),('pg',['tests/test_g7_memory_api_pg.py','-k',select])]
if '--redis' in sys.argv:
    from urllib.parse import urlsplit
    from redis import Redis
    redis_url=urlsplit(env['REDIS_URL'])._replace(path='/15').geturl()
    with Redis.from_url(redis_url) as redis:
        assert redis.dbsize()==0,'Logical test DB15 is not empty; leave existing keys untouched'
    env.update(TEST_CHAT_REDIS_URL=redis_url,G8_ENABLED='false')
    commands=[('redis',['tests/test_g7_memory_api_pg.py','-k','memory_edit_invalidates_old_redis_candidates'])]
for label,args in commands:
    cmd=['uv','run','--frozen','--no-sync','python','-B','-m','pytest',*args,'-q','--tb=short','-p','no:cacheprovider','--basetemp='+str(Path(os.environ['TEMP'])/('g8-investigation-'+label)),'-o','junit_family=legacy','--junitxml='+str(OUT/(P+label+'.xml'))]
    with (OUT/(P+label+'.log')).open('wb') as log:
        result=subprocess.run(cmd,cwd=ROOT/'backend/chatbot',env=env,stdout=log,stderr=subprocess.STDOUT)
    print(label,'exit',result.returncode,flush=True)
    if result.returncode:raise SystemExit(result.returncode)
