import importlib.util,subprocess,json
from pathlib import Path
p=Path('../../reports/g8/parent/completion-restore-app-run.py').resolve()
s=importlib.util.spec_from_file_location('run',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
e=m.environment()
f=open(m.OUT/'completion-restore-api.log','ab')
a=subprocess.Popen([str(m.ROOT/'backend/api/.venv/Scripts/python.exe'),'-B',str(p),'api'],cwd=m.ROOT/'backend/api',env=e,stdout=f,stderr=f,creationflags=subprocess.CREATE_NO_WINDOW)
w=dict(e,EXPO_PUBLIC_API_BASE_URL='http://localhost:19834',EXPO_PUBLIC_CHAT_API_BASE_URL='http://localhost:19833',EXPO_PUBLIC_SUPABASE_URL=e['SUPABASE_URL'],EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=e['SUPABASE_PUBLISHABLE_KEY'],CI='1')
f2=open(m.OUT/'completion-restore-web.log','ab')
b=subprocess.Popen(['node','node_modules/expo/bin/cli','start','--web','--port','19836','--localhost','--clear'],cwd=m.ROOT,env=w,stdout=f2,stderr=f2,creationflags=subprocess.CREATE_NO_WINDOW)
(m.OUT/'completion-restore-web-api-runtime.json').write_text(json.dumps({'apiPid':a.pid,'webPid':b.pid}),encoding='utf-8')
print('current API/web',a.pid,b.pid)
