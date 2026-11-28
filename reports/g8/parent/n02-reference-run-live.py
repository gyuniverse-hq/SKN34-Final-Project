"""Approved synthetic reference utterances; credentials stay in child environment."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
values = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
assert values["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
assert values["LLM_MODEL"] == "gpt-6-luna"
env = dict(os.environ, PYTHONUTF8="1", G8_N02_REFERENCE_LIVE="1")
for key in ["LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"]:
    env[key] = values[key]
print("Destination: api.openai.com; model: gpt-6-luna; synthetic utterances and catalog fixture only", flush=True)
result = subprocess.run([sys.executable, "-m", "pytest", "tests/test_g8_owned_look_interpreter.py::test_live_model_reference_contract", "-q", "--tb=short", "-o", "junit_family=legacy", "--junitxml=" + str(root / "reports/g8/parent/n02-reference-live-final.xml")], cwd=root / "backend/chatbot", env=env)
raise SystemExit(result.returncode)
