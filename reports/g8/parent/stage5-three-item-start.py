import hashlib,importlib.util,json,subprocess,socket,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent'
raw=subprocess.check_output(['pwsh','-NoProfile','-Command',"Get-NetTCPConnection -State Listen -LocalPort 19833 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {Get-CimInstance Win32_Process -Filter ('ProcessId = '+$_)} | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],text=True).strip()
if raw:
 procs=json.loads(raw);procs=procs if isinstance(procs,list) else [procs]
 for p in procs:
  assert 'stage5-three-item-runtime.py chat' in p['CommandLine'], 'Other listener left untouched'
  subprocess.run(['pwsh','-NoProfile','-Command',f"Stop-Process -Id {int(p['ProcessId'])}"],check=True)
manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((ROOT/'backend/chatbot/app').rglob('*.py'))]
(OUT/'stage5-three-item-release-sources.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
s=importlib.util.spec_from_file_location('runtime',OUT/'stage5-three-item-runtime.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
proc=subprocess.Popen([str(ROOT/'backend/chatbot/.venv/Scripts/python.exe'),'-B',str(OUT/'stage5-three-item-runtime.py'),'chat'],cwd=ROOT/'backend/chatbot',env=m.environment(),stdout=open(OUT/'stage5-three-item-app-chat.log','ab'),stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
for _ in range(20):
 try:
  with socket.create_connection(('127.0.0.1',19833),timeout=1):break
 except OSError:time.sleep(.5)
else:raise SystemExit('Chat not ready')
print('READY final-source chat',proc.pid)
