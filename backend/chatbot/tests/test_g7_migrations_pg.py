import os
import subprocess
import sys
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import URL, make_url

TEST_URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_URL, reason="TEST_CHAT_DATABASE_URL not set"),
]


def _dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture
def migration_url():
    if os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1":
        pytest.skip("requires explicit authorization to create and drop a disposable database")

    base_url = make_url(TEST_URL)
    if (
        base_url.drivername != "postgresql+asyncpg"
        or base_url.host not in {"localhost", "127.0.0.1", "::1"}
        or base_url.database != "vishue_chat_test"
        or base_url.query
    ):
        pytest.fail("migration tests require a local, disposable vishue_chat_test configuration")

    # CI's local PostgreSQL role can create databases. Never downgrade the suite's shared DB.
    name = f"vishue_g7_migration_{uuid4().hex}"
    with psycopg.connect(_dsn(base_url.set(database="postgres")), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        try:
            yield base_url.set(database=name)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def _alembic(url: URL, *args: str, expected_error: str | None = None) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={
            **os.environ,
            "CHAT_DATABASE_URL": url.render_as_string(hide_password=False),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    diagnostic = (
        f"alembic {' '.join(args)} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    if expected_error is None:
        assert result.returncode == 0, diagnostic
    else:
        assert result.returncode != 0 and expected_error in result.stderr, diagnostic


def test_migration_upgrade_downgrade_and_model_consistency(migration_url):
    _alembic(migration_url, "upgrade", "head")
    _alembic(migration_url, "downgrade", "base")
    with psycopg.connect(_dsn(migration_url)) as conn:
        assert conn.execute("SELECT to_regclass('public.chat_owner_status')").fetchone() == (None,)
    _alembic(migration_url, "upgrade", "head")
    _alembic(migration_url, "check")


@pytest.mark.parametrize(
    ("settings_changed", "expected_error"),
    [
        (True, "Use a compatible application to roll back memory settings"),
        (False, "Use a compatible application to roll back structured memories"),
    ],
    ids=["memory-settings", "structured-memory"],
)
def test_populated_database_refuses_downgrade_without_losing_data(
    migration_url, settings_changed, expected_error
):
    _alembic(migration_url, "upgrade", "head")
    memory_id = uuid4()
    owner_id = "g7-migration-owner"
    value = {"value": "dry"}
    with psycopg.connect(_dsn(migration_url)) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        conn.execute(
            "INSERT INTO chat_owner_status (owner_id, memory_enabled) VALUES (%s, %s)",
            (owner_id, not settings_changed),
        )
        if not settings_changed:
            conn.execute(
                """
                INSERT INTO chat_memories (
                    id, owner_id, kind, memory_key, value_json, consent_scope, confirmed_at,
                    schema_version, registry_version, semantic_key, display_value,
                    applicability_json
                ) VALUES (
                    %s, %s, 'profile', 'skin-type', %s, 'future_consultations', now(),
                    2, 1, 'skin.type', 'Dry', '{}'::jsonb
                )
                """,
                (memory_id, owner_id, Jsonb(value)),
            )

    _alembic(migration_url, "downgrade", "base", expected_error=expected_error)

    with psycopg.connect(_dsn(migration_url)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == version
        assert conn.execute(
            "SELECT memory_enabled FROM chat_owner_status WHERE owner_id = %s",
            (owner_id,),
        ).fetchone() == (not settings_changed,)
        if not settings_changed:
            assert conn.execute(
                "SELECT schema_version, value_json FROM chat_memories WHERE id = %s",
                (memory_id,),
            ).fetchone() == (2, value)
