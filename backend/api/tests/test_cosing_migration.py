"""The develop-based CosIng migration is additive and preserves shared data."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

VERSIONS = Path(__file__).resolve().parents[1] / "alembic"
TABLES = {"cosing_function", "cosing_ingredient_lookup", "ingredient_function", "function_concern"}


def scripts():
    config = Config()
    config.set_main_option("script_location", str(VERSIONS))
    return ScriptDirectory.from_config(config)


def test_cosing_follows_develop_geometry_in_a_single_migration_chain():
    directory = scripts()
    assert len(directory.get_heads()) == 1
    assert directory.get_revision("0018").down_revision == "0017"
    assert Path(directory.get_revision("0017").path).name == "0017_look_ar_geometry.py"
    assert "0018" in {revision.revision for revision in directory.walk_revisions()}


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("COSING_MIGRATION_TEST_URL"), reason="needs test PostgreSQL")
def test_upgrade_and_downgrade_preserve_existing_data_and_concern_labels():
    def verify(conn):
        # Rollback-only schema: no production tables or Alembic version are modified.
        schema = "cosing_test_" + uuid4().hex
        conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        conn.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
        for sql in (
            "CREATE TABLE raw_mfds_ingredient (ingredient_id bigint PRIMARY KEY)",
            "CREATE TABLE rec_concern (target_concern text PRIMARY KEY, "
            "display_label text NOT NULL, recommendation_reason text NOT NULL)",
            "CREATE TABLE rec_mapping (mapping_id text PRIMARY KEY, "
            "target_concern text REFERENCES rec_concern)",
            "CREATE TABLE skincare_serving (id integer PRIMARY KEY, payload jsonb)",
            "INSERT INTO raw_mfds_ingredient VALUES (42)",
            "INSERT INTO rec_concern VALUES ('pores', 'preserved label', 'preserved reason')",
            "INSERT INTO rec_mapping VALUES ('existing-research', 'pores')",
            "INSERT INTO skincare_serving VALUES (1, jsonb_build_object('preserved', true))",
        ):
            conn.execute(sa.text(sql))
        migration = scripts().get_revision("0018").module
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert set(sa.inspect(conn).get_table_names(schema=schema)) >= TABLES
            assert conn.scalar(sa.text("SELECT count(*) FROM rec_concern")) == 7
            assert conn.execute(sa.text(
                "SELECT display_label, recommendation_reason FROM rec_concern "
                "WHERE target_concern='pores'"
            )).one() == ("preserved label", "preserved reason")
            conn.execute(sa.text(
                "INSERT INTO cosing_function (function_name) VALUES ('ASTRINGENT')"
            ))
            conn.execute(sa.text(
                "INSERT INTO cosing_ingredient_lookup (ingredient_id, status, match_method) "
                "VALUES (42, 'accepted', 'exact')"
            ))
            conn.execute(sa.text("INSERT INTO ingredient_function VALUES (42, 1)"))
            conn.execute(sa.text("INSERT INTO function_concern VALUES (1, 'pores')"))
            assert conn.scalar(sa.text(
                "SELECT count(*) FROM ingredient_function JOIN function_concern USING(function_id)"
            )) == 1
            migration.downgrade()
            assert not TABLES & set(sa.inspect(conn).get_table_names(schema=schema))
            assert conn.scalar(sa.text("SELECT mapping_id FROM rec_mapping")) == "existing-research"
            payload = conn.scalar(sa.text("SELECT payload FROM skincare_serving"))
            assert payload == {"preserved": True}
            assert conn.scalar(sa.text("SELECT count(*) FROM rec_concern")) == 7
            migration.upgrade()
            assert conn.scalar(sa.text("SELECT count(*) FROM rec_concern")) == 7

    async def run():
        engine = create_async_engine(os.environ["COSING_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.run_sync(verify)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
