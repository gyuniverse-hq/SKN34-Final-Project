"""Fresh current-source Expo bundle on the existing validation origin; no auth data saved."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
spec=importlib.util.spec_from_file_location('runtime',OUT/'question-scope-answer-app-run.py')
runtime=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
base=runtime.environment()
env=dict(os.environ,EXPO_NO_TELEMETRY='1',EXPO_PUBLIC_API_BASE_URL='http://localhost:19834',
    EXPO_PUBLIC_CHAT_API_BASE_URL='http://localhost:19833',
    EXPO_PUBLIC_SUPABASE_URL=base['SUPABASE_URL'],
    EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=base['SUPABASE_PUBLISHABLE_KEY'])
env.pop('CI',None)
paths=[p for folder in ['app','components','hooks','lib','store','types','constants']
       for p in (ROOT/folder).rglob('*') if p.suffix in {'.ts','.tsx'}]
source=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(paths)]
log=open(OUT/'question-scope-answer-web-current.log','ab')
proc=subprocess.Popen(['node','node_modules/expo/bin/cli','start','--web','--port','19836','--localhost','--clear'],
    cwd=ROOT,env=env,stdout=log,stderr=log,stdin=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW)
(OUT/'question-scope-answer-web-current.json').write_text(json.dumps({
    'at':datetime.now(timezone.utc).isoformat(),'pid':proc.pid,'watchMode':True,'sourceSha256':source},indent=2),encoding='utf-8')
print('Started verified current-source web',proc.pid)
