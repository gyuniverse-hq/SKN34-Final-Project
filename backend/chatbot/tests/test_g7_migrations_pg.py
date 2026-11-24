import os
import subprocess
import sys

import pytest
from sqlalchemy.engine import make_url

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
]


def test_migration_upgrade_downgrade_and_model_consistency():
    if (
        make_url(URL).database != "vishue_chat_test"
        or os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1"
    ):
        pytest.skip("requires explicitly authorized disposable vishue_chat_test database")
    env = {**os.environ, "CHAT_DATABASE_URL": URL, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            env=env,
            check=True,
            capture_output=True,
        )
    finally:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        [sys.executable, "-m", "alembic", "check"], env=env, check=True, capture_output=True
    )
