"""Temporary current-source G5 API over the existing authenticated integration DB."""
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
for key in ("G5_OPENAI_API_KEY", "G5_INTERNAL_TOKEN"):
    os.environ[key] = private[key]
url = make_url(private["DATABASE_URL"]).set(host="172.24.16.240", port=19841)
os.environ.update(DATABASE_URL=url.render_as_string(hide_password=False), ENV="local",
    G5_ENABLED="true", G5_ALLOW_LOCAL_SOURCES="true", SKINCARE_REFRESH_ENABLED="false",
    LOG_LEVEL="WARNING")
sys.path.insert(0, str(ROOT / "backend/api"))
from app.main import create_app
import uvicorn

uvicorn.run(create_app(), host="127.0.0.1", port=19838, access_log=False, log_level="warning")
