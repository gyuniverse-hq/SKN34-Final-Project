"""Exercise the real 0020 tables in a rollback-only, private PostgreSQL schema."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.errors import ApiError
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.schemas.recommendation_feedback import RecordedComparisonInput
from app.services.recommendation_feedback_service import RecommendationFeedbackService
from app.services.recommendation_v2_service import rank_products
from tests.test_recommendation_comparison import body, catalog, option
from tests.test_recommendation_feedback import event, impression


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RECOMMENDATION_FEEDBACK_MIGRATION_TEST_URL"),
    reason="needs an isolated test PostgreSQL",
)
def test_recorded_run_impressions_events_ownership_retries_and_delete():
    config = Config()
    config.set_main_option("script_location", "alembic")
    migration = ScriptDirectory.from_config(config).get_revision("0020").module

    def create_tables(connection):
        schema = "rec_flow_test_" + uuid4().hex
        connection.execute(sa.text(f"CREATE SCHEMA {schema}"))
        connection.execute(sa.text(f"SET LOCAL search_path TO {schema}"))
        connection.execute(sa.text("CREATE TABLE members (id varchar(64) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE order_lines (id integer PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO members VALUES ('owner'), ('other')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async def compare(_body, *, audit):
        data = catalog([option(f"p{i}", [1]) for i in range(7)])
        ranked = rank_products([{"id": 1, "score": 0.8}], [], data, "pores", audit=audit)
        return {
            "v2": {"status": "ok", **ranked},
            "versions": {"catalogVersion": data.version, "catalogDigest": data.digest},
        }

    async def verify(connection):
        await connection.run_sync(create_tables)
        # Repository commit() releases savepoints, never commits the outer test transaction.
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            repository = RecommendationFeedbackRepository(session)
            service = RecommendationFeedbackService(
                repository,
                SimpleNamespace(get=AsyncMock(return_value=True)),
                SimpleNamespace(compare=compare),
                "test",
            )
            request = RecordedComparisonInput(session_id=uuid4(), input=body())
            result = await service.compare(request, "owner")
            assert len(result["v2"]["matches"]) == 5
            assert (
                await connection.scalar(sa.text("SELECT count(*) FROM recommendation_candidates"))
                == 7
            )
            assert (
                await connection.scalar(sa.text("SELECT status FROM recommendation_requests"))
                == "completed"
            )
            selected = result["v2"]["matches"][0]
            exposure = impression(
                candidateId=selected["candidateId"], displayedPosition=selected["rank"]
            )
            hidden_id = await connection.scalar(
                sa.text(
                    "SELECT candidate_id FROM recommendation_candidates "
                    "WHERE final_rank IS NULL LIMIT 1"
                )
            )
            with pytest.raises(ApiError):
                await service.impression(impression(candidateId=str(hidden_id)), "owner")
            with pytest.raises(ApiError):
                await service.impression(exposure, "other")
            action = event(
                impressionId=str(exposure.impression_id),
                sessionId=str(request.session_id),
                productId=selected["productId"],
                optionId=selected["optionId"],
            )
            with pytest.raises(ApiError):
                await service.event(action, "owner")  # out-of-order is not fabricated
            await service.impression(exposure, "owner")
            await service.impression(exposure, "owner")
            with pytest.raises(ApiError):
                await service.impression(
                    exposure.model_copy(update={"impression_id": uuid4()}), "owner"
                )
            await service.event(action, "owner")
            await service.event(action, "owner")
            with pytest.raises(ApiError):
                await service.event(
                    action.model_copy(update={"event_type": "outbound_click"}), "owner"
                )
            with pytest.raises(ApiError):
                await service.event(action, "other")
            await service.event(
                event(
                    impressionId=str(exposure.impression_id),
                    sessionId=str(request.session_id),
                    productId=selected["productId"],
                    optionId=None,
                    eventType="cart_add",
                ),
                "owner",
            )
            assert (
                await connection.scalar(sa.text("SELECT count(*) FROM recommendation_impressions"))
                == 1
            )
            assert (
                await connection.scalar(sa.text("SELECT count(*) FROM user_behavior_events")) == 2
            )
            service.comparison = SimpleNamespace(
                compare=AsyncMock(
                    return_value={
                        "v2": {"status": "v2_failed", "matches": []},
                        "versions": {},
                    }
                )
            )
            await service.compare(request, "owner")
            assert (
                await connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM recommendation_requests "
                        "WHERE status = 'failed' AND model_manifest IS NULL"
                    )
                )
                == 1
            )
            await session.execute(sa.text("DELETE FROM members WHERE id = 'owner'"))
            await session.commit()
            for table in (
                "recommendation_requests",
                "recommendation_candidates",
                "recommendation_impressions",
                "user_behavior_events",
            ):
                assert await connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0

    async def run():
        engine = create_async_engine(os.environ["RECOMMENDATION_FEEDBACK_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    await verify(connection)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
