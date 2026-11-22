"""Verify AR history constraints and member deletion in an isolated PostgreSQL schema."""

import asyncio
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AR_PERSONALIZATION_MIGRATION_TEST_URL"),
    reason="needs an isolated test PostgreSQL connection",
)
def test_ar_history_is_deduplicated_and_removed_with_member():
    config = Config()
    config.set_main_option("script_location", "alembic")
    migration = ScriptDirectory.from_config(config).get_revision("0023").module

    def verify(connection):
        schema = "ar_history_test_" + uuid4().hex
        connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
        connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
        connection.execute(sa.text("CREATE TABLE members (id varchar(64) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO members (id) VALUES ('member-1')"))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

            request, candidate, impression, session, view, event, free_event = (
                str(uuid4()) for _ in range(7)
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ar_recommendation_requests "
                    "(request_id, member_id, session_id, makeup_zone, strategy, policy_version) "
                    "VALUES (:id, 'member-1', :session, 'lip', 'rating', 'v1')"
                ),
                {"id": request, "session": session},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ar_recommendation_candidates "
                    "(candidate_id, request_id, product_id, shade_id, rank) "
                    "VALUES (:id, :request, 'product-1', 'shade-1', 1)"
                ),
                {"id": candidate, "request": request},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ar_recommendation_impressions "
                    "(impression_id, candidate_id, view_instance_id, displayed_position, "
                    "occurred_at, visibility_policy_version) "
                    "VALUES (:id, :candidate, :view, 1, now(), 'v1')"
                ),
                {"id": impression, "candidate": candidate, "view": view},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ar_activity_events "
                    "(event_id, member_id, session_id, product_id, shade_id, makeup_zone, "
                    "event_type, impression_id, occurred_at, schema_version) "
                    "VALUES (:id, 'member-1', :session, 'product-1', 'shade-1', 'lip', "
                    "'try_on', :impression, now(), 'v1')"
                ),
                {"id": event, "session": session, "impression": impression},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ar_activity_events "
                    "(event_id, member_id, session_id, product_id, shade_id, makeup_zone, "
                    "event_type, occurred_at, schema_version) "
                    "VALUES (:id, 'member-1', :session, 'product-1', 'shade-1', 'lip', "
                    "'cart_add', now(), 'v1')"
                ),
                {"id": free_event, "session": session},
            )
            assert connection.scalar(sa.text("SELECT count(*) FROM ar_activity_events")) == 2

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.text(
                        "INSERT INTO ar_recommendation_candidates "
                        "(candidate_id, request_id, product_id, shade_id, rank) "
                        "VALUES (:id, :request, 'product-1', 'shade-1', 2)"
                    ),
                    {"id": str(uuid4()), "request": request},
                )

            connection.execute(sa.text("DELETE FROM members WHERE id = 'member-1'"))
            for table in (
                "ar_recommendation_requests",
                "ar_recommendation_candidates",
                "ar_recommendation_impressions",
                "ar_activity_events",
            ):
                assert connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0

            migration.downgrade()
            assert set(sa.inspect(connection).get_table_names(schema=schema)) == {"members"}

    async def run():
        engine = create_async_engine(os.environ["AR_PERSONALIZATION_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await connection.run_sync(verify)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
