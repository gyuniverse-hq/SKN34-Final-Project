"""Exercise deletion of a member's recommendation history in an isolated schema."""

import asyncio
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RECOMMENDATION_FEEDBACK_MIGRATION_TEST_URL"),
    reason="needs an isolated test PostgreSQL",
)
def test_member_deletion_removes_recommendation_history_and_preserves_orders():
    config = Config()
    config.set_main_option("script_location", "alembic")
    migration = ScriptDirectory.from_config(config).get_revision("0020").module

    def verify(connection):
        schema = "rec_feedback_test_" + uuid4().hex
        connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
        connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
        connection.execute(sa.text("CREATE TABLE members (id varchar(64) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE order_lines (id integer PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO members (id) VALUES ('member-1')"))
        connection.execute(sa.text("INSERT INTO order_lines (id) VALUES (7)"))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

            request_id, candidate_id, impression_id, event_id, session_id = (
                str(uuid4()) for _ in range(5)
            )
            connection.execute(
                sa.text(
                    "INSERT INTO recommendation_requests "
                    "(request_id, member_id, session_id, status, environment, input_snapshot, "
                    "primary_concern, contract_version, feature_version, ranking_policy_version, "
                    "policy_snapshot) VALUES "
                    "(:id, 'member-1', :session, 'started', 'test', '{}'::jsonb, "
                    "'dryness', 'v1', 'v1', 'v1', '{}'::jsonb)"
                ),
                {"id": request_id, "session": session_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO recommendation_candidates "
                    "(candidate_id, request_id, product_id, option_id, "
                    "primary_ingredient_score, ingredient_score, review_score, v2_score, "
                    "evidence_snapshot) VALUES "
                    "(:id, :request, 'oy-test', 'option-test', 0.5, 0.5, 0.5, 0.5, '{}'::jsonb)"
                ),
                {"id": candidate_id, "request": request_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO recommendation_impressions "
                    "(impression_id, candidate_id, view_instance_id, surface, displayed_position, "
                    "occurred_at, visibility_policy_version) VALUES "
                    "(:id, :candidate, :view, 'recommendations', 1, now(), 'v1')"
                ),
                {"id": impression_id, "candidate": candidate_id, "view": str(uuid4())},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO user_behavior_events "
                    "(event_id, member_id, session_id, impression_id, order_line_id, product_id, "
                    "event_type, event_source, occurred_at, event_schema_version, surface, "
                    "context_snapshot) VALUES "
                    "(:id, 'member-1', :session, :impression, 7, 'oy-test', "
                    "'product_view', 'client', now(), 'v1', 'recommendations', '{}'::jsonb)"
                ),
                {
                    "id": event_id,
                    "session": session_id,
                    "impression": impression_id,
                },
            )
            connection.execute(sa.text("DELETE FROM members WHERE id = 'member-1'"))
            for table in (
                "recommendation_requests",
                "recommendation_candidates",
                "recommendation_impressions",
                "user_behavior_events",
            ):
                assert connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0
            assert connection.scalar(sa.text("SELECT count(*) FROM order_lines")) == 1

            migration.downgrade()
            remaining = set(sa.inspect(connection).get_table_names(schema=schema))
            assert remaining == {"members", "order_lines"}

    async def run():
        engine = create_async_engine(os.environ["RECOMMENDATION_FEEDBACK_MIGRATION_TEST_URL"])
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
