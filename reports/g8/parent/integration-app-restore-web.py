"""Restart only the approved local web verifier with a fresh Metro cache."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import socket
import hashlib
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
for host in ("127.0.0.1", "::1"):
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
        probe.settimeout(1)
        if probe.connect_ex((host, 19836)) == 0:
            raise SystemExit("Port 19836 is already serving; verify and stop its owner before restarting")
base = runpy.run_path(str(OUT / "integration-n02-app-run.py"))["environment"]()
env = dict(os.environ, CI="1", EXPO_NO_TELEMETRY="1",
    EXPO_PUBLIC_API_BASE_URL="http://localhost:19834",
    EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833",
    EXPO_PUBLIC_SUPABASE_URL=base["SUPABASE_URL"],
    EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=base["SUPABASE_PUBLISHABLE_KEY"])
with open(OUT / "integration-app-restore-web-web.log", "ab") as log:
    proc = subprocess.Popen(["node", "node_modules/expo/bin/cli", "start", "--web", "--port", "19836", "--localhost", "--clear"], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
(OUT / "integration-app-restore-web-web-runtime.json").write_text(json.dumps({"pid": proc.pid, "port": 19836, "cwd": str(ROOT), "at": datetime.now(timezone.utc).isoformat(), "ci": True, "cacheCleared": True,
    "sourceSha256": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in ["hooks/useChatConversations.ts", "lib/api.ts", "app/chat.tsx"]]}), encoding="utf-8")
print("Started fresh local web verifier", proc.pid)
