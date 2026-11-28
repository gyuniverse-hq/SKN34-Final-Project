import importlib.util,subprocess,json
from pathlib import Path
p=Path('reports/g8/parent/completion-restore-app-run.py').resolve();s=importlib.util.spec_from_file_location('r',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
e=m.environment();e.update(EXPO_PUBLIC_API_BASE_URL='http://localhost:19834',EXPO_PUBLIC_CHAT_API_BASE_URL='http://localhost:19833',EXPO_PUBLIC_SUPABASE_URL=e['SUPABASE_URL'],EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=e['SUPABASE_PUBLISHABLE_KEY'],CI='1')
f=open(m.OUT/'completion-restore-web-final.log','ab')
r=subprocess.Popen(['node','node_modules/expo/bin/cli','start','--web','--port','19836','--localhost','--clear'],cwd=m.ROOT,env=e,stdout=f,stderr=f,creationflags=subprocess.CREATE_NO_WINDOW)
print('final web',r.pid)
