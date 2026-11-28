"""Start only the approved local validation services; reuse running Catalog and DB."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
spec = importlib.util.spec_from_file_location("runtime", OUT / "question-scope-answer-app-run.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
env = runtime.environment()
web = dict(os.environ, CI="1", EXPO_NO_TELEMETRY="1",
    EXPO_PUBLIC_API_BASE_URL="http://localhost:19834",
    EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833",
    EXPO_PUBLIC_SUPABASE_URL=env["SUPABASE_URL"],
    EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env["SUPABASE_PUBLISHABLE_KEY"])
commands = {
    "g5": ([str(ROOT / "backend/api/.venv/Scripts/python.exe"), "-B",
            str(OUT / "question-scope-answer-g5-api.py")], ROOT / "backend/api", env),
    "chat": ([str(ROOT / "backend/chatbot/.venv/Scripts/python.exe"), "-B",
              str(OUT / "question-scope-answer-app-run.py"), "chat"], ROOT / "backend/chatbot", env),
    "web": (["node", "node_modules/expo/bin/cli", "start", "--web", "--port", "19836", "--localhost"], ROOT, web)
}
pids = {}
for role, (cmd, cwd, process_env) in commands.items():
    log = open(OUT / f"question-scope-answer-{role}.log", "ab")
    proc = subprocess.Popen(cmd, cwd=cwd, env=process_env, stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    pids[role] = proc.pid
(OUT / "question-scope-answer-runtime.json").write_text(json.dumps({
    "pids": pids, "configuredMode": "live", "model": env["LLM_MODEL"],
    "startedAt": datetime.now(timezone.utc).isoformat(), "db": "vishue_g8_browser",
    "catalog": "http://127.0.0.1:19834"}, indent=2), encoding="utf-8")
print(pids)
