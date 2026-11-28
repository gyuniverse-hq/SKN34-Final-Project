"""Local disposable PG + live read-only Catalog verification; no credentials in output."""
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy.engine import make_url
import psycopg

ROOT = Path(__file__).resolve().parents[3]
info = json.loads(subprocess.check_output(["docker", "inspect", "vishue-api-1"], text=True))[0]
env = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
url = make_url(env["DATABASE_URL"]).set(host="127.0.0.1", port=15434, database="vishue_chat_test")
# Only the disposable test database may receive test records.
admin_url = url.set(database="postgres", drivername="postgresql")
with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as conn:
    if not conn.execute("select 1 from pg_database where datname = %s", ("vishue_chat_test",)).fetchone():
        conn.execute("CREATE DATABASE vishue_chat_test")
        print("Created isolated vishue_chat_test database", flush=True)
with psycopg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False)) as conn:
    assert conn.execute("select current_database()").fetchone()[0] == "vishue_chat_test"
    print("Disposable PostgreSQL: vishue_chat_test, port 15434", flush=True)
child = dict(os.environ, TEST_CHAT_DATABASE_URL=url.render_as_string(hide_password=False),
             G8_N02_LIVE_CATALOG="http://127.0.0.1:19834", PYTHONUTF8="1")
child["CHAT_DATABASE_URL"] = url.render_as_string(hide_password=False)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend/chatbot", env=child, check=True)
subprocess.run([sys.executable, "-m", "app.jobs.init_chat_checkpoints"], cwd=ROOT / "backend/chatbot", env=child, check=True)
live = "--live" in sys.argv
if live:
    chat = json.loads(subprocess.check_output(["docker", "inspect", "vishue-chatbot-1"], text=True))[0]
    values = dict(v.split("=", 1) for v in chat["Config"]["Env"] if "=" in v)
    assert values["LLM_BASE_URL"].rstrip("/") == "https://api.openai.com/v1"
    for key in ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"]:
        child[key] = values[key]
    child["G8_COMPARISON_SELECTION_LIVE"] = "1"
    child["G8_CURRENT_PRICE_FOLLOWUP"] = "1"

child["G8_EXECUTION_LIVE"] = "1" if live else "0"
result = subprocess.run([sys.executable, "-m", "pytest", "tests/test_g7_conversation_api_pg.py",  "-q", "--tb=short", "-o", "junit_family=legacy", "--junitxml="+str(ROOT/"reports/g8/parent"/("common-execution-control-live.xml" if live else "common-execution-control-pg-regression.xml"))], cwd=ROOT/"backend/chatbot",env=child)
raise SystemExit(result.returncode)
