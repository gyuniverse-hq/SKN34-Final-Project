"""Validation-only launcher; reuses existing credentials in memory, never prints them."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
spec = importlib.util.spec_from_file_location("runtime", OUT / "stage6-remediation-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
env = runtime.environment()
env["PYTHONDONTWRITEBYTECODE"] = "1"
for port in (19833, 19836, 19838, 19841):
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0, "Existing listener left untouched"
pids = {}
linux_root = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
commands = {
    "relay": (["wsl", "-d", "vishue-g5", "--", "python3", "-B", "-u", linux_root + "/reports/g8/parent/stage6-remediation-relay.py", "172.24.16.240"], ROOT),
    "g5": ([str(ROOT / "backend/api/.venv/Scripts/python.exe"), "-B", str(OUT / "stage6-remediation-g5-api.py")], ROOT / "backend/api"),
    "chat": ([sys.executable, "-B", str(OUT / "stage6-remediation-runtime.py"), "chat"], ROOT / "backend/chatbot"),
}
for role, (command, cwd) in commands.items():
    with open(OUT / f"stage6-remediation-{role}.log", "ab") as log:
        pids[role] = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW).pid
web = dict(os.environ, CI="1", EXPO_NO_TELEMETRY="1", EXPO_PUBLIC_API_BASE_URL="http://localhost:19834", EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833", EXPO_PUBLIC_SUPABASE_URL=env["SUPABASE_URL"], EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env["SUPABASE_PUBLISHABLE_KEY"])
with open(OUT / "stage6-remediation-web.log", "ab") as log:
    pids["web"] = subprocess.Popen(["node", "node_modules/expo/bin/cli", "start", "--web", "--port", "19836", "--localhost"], cwd=ROOT, env=web, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW).pid
for port in (19833, 19838):
    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit(f"Validation service not ready: {port}; inspect scoped log")
(OUT / "stage6-remediation-runtime.json").write_text(json.dumps({"pids": pids, "ports": {"chat": 19833, "catalog": 19834, "web": 19836, "g5": 19838, "relay": 19841}, "modelConfiguredMode": "live", "auth": "existing actual Supabase session", "chatDatabase": "vishue_g8_browser"}, indent=2), encoding="utf-8")
print("Validation services ready; credentials withheld; scoped PIDs", pids)
