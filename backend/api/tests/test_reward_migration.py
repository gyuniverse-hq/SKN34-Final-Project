"""Verify the attendance/coupon schema contract, not payment feature behavior."""

import asyncio
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.environment import EnvironmentContext
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app.core.db import Base


def migration():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    return ScriptDirectory.from_config(config).get_revision("0038").module


def render(operation):
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect=postgresql.dialect(), opts={"as_sql": True, "output_buffer": buffer}
    )
    with Operations.context(context):
        operation()
    return buffer.getvalue()


def test_reward_metadata_and_migration():
    assert migration().down_revision == "0037"
    metadata = Base.metadata.tables
    assert list(metadata["reward_attendance"].c.keys()) == [
        "member_id",
        "attendance_date",
        "stamp_goal",
    ]
    assert list(metadata["reward_coupons"].c.keys()) == [
        "id",
        "member_id",
        "source_date",
        "issued_at",
        "expires_at",
    ]
    assert [c.name for c in metadata["reward_attendance"].primary_key] == [
        "member_id",
        "attendance_date",
    ]
    coupon = metadata["orders"].c.reward_coupon_id
    assert coupon.nullable and next(iter(coupon.foreign_keys)).ondelete == "SET NULL"
    assert not metadata["orders"].c.discount_krw.nullable
    indexes = {i.name: i for i in metadata["orders"].indexes}
    assert indexes["ux_orders_active_reward_coupon"].unique
    sql = render(migration().upgrade)
    assert "ON DELETE CASCADE" in sql and "ON DELETE SET NULL" in sql
    assert "UNIQUE INDEX ux_orders_active_reward_coupon" in sql
    assert "reward_coupon_id IS NOT NULL AND status <> 'canceled'" in sql
    assert "discount_krw BETWEEN 0 AND 2000" in sql
    assert "ALTER TABLE reward_attendance ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE reward_coupons ENABLE ROW LEVEL SECURITY" in sql
    assert not any(phrase in sql for phrase in ("UPDATE orders", "DELETE FROM", "INSERT INTO"))
    downgrade = render(migration().downgrade)
    assert downgrade.index("DROP TABLE reward_coupons") < downgrade.index(
        "DROP TABLE reward_attendance"
    )
    assert "DROP TABLE orders" not in downgrade and "DROP TABLE members" not in downgrade


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("ATTENDANCE_MIGRATION_TEST_URL"), reason="needs test PostgreSQL"
)
def test_reward_constraints_preserve_orders_and_member_deletion():
    def exercise(conn):
        schema = "reward_test_" + uuid4().hex
        conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        conn.execute(sa.text(f"SET LOCAL search_path TO {schema}"))

        def execute(sql):
            return conn.execute(sa.text(sql))

        def rejected(sql):
            with pytest.raises(IntegrityError), conn.begin_nested():
                execute(sql)

        execute(
            "CREATE TABLE members (id varchar(64) PRIMARY KEY, skin_subscription_until timestamptz)"
        )
        execute(
            "CREATE TABLE orders (id varchar(64) PRIMARY KEY, user_id varchar(64) NOT NULL, "
            "status varchar(20) NOT NULL, amount_krw integer NOT NULL)"
        )
        execute(
            "CREATE TABLE order_lines (id integer PRIMARY KEY, order_id varchar(64) "
            "REFERENCES orders(id), unit_price_krw integer NOT NULL, quantity integer NOT NULL)"
        )
        execute("INSERT INTO members(id) VALUES ('member-a'), ('member-b')")
        execute("INSERT INTO orders VALUES ('legacy','member-a','paid',12000)")
        execute("INSERT INTO order_lines VALUES (1,'legacy',6000,2)")
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
            assert tuple(
                execute(
                    "SELECT amount_krw,reward_coupon_id,discount_krw FROM orders WHERE id='legacy'"
                ).one()
            ) == (12000, None, 0)
            assert (
                execute(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() AND c.relname IN "
                    "('reward_attendance','reward_coupons') AND c.relrowsecurity"
                ).scalar_one()
                == 2
            )
            execute("INSERT INTO reward_attendance VALUES ('member-a','2026-11-25',4)")
            rejected("INSERT INTO reward_attendance VALUES ('member-a','2026-11-25',7)")
            rejected("INSERT INTO reward_attendance VALUES ('member-a','2026-11-26',5)")
            rejected("INSERT INTO reward_attendance VALUES ('missing','2026-11-25',7)")
            coupon = str(uuid4())
            other = str(uuid4())
            values = "'member-a','2026-11-25','2026-11-25 09:00+09','2026-12-02 00:00+09'"
            execute(f"INSERT INTO reward_coupons VALUES ('{coupon}',{values})")
            rejected(f"INSERT INTO reward_coupons VALUES ('{other}',{values})")
            rejected(
                f"INSERT INTO reward_coupons VALUES ('{other}','member-b','2026-11-25',"
                "'2026-11-25 09:00+09','2026-12-02 00:00+09')"
            )
            execute("INSERT INTO reward_attendance VALUES ('member-a','2026-11-26',7)")
            rejected(
                f"INSERT INTO reward_coupons VALUES ('{other}','member-a','2026-11-26',"
                "'2026-11-26 09:00+09','2026-11-26 09:00+09')"
            )
            execute(f"INSERT INTO orders VALUES ('one','member-a','pending',18000,'{coupon}',2000)")
            rejected(
                f"INSERT INTO orders VALUES ('two','member-a','pending',18000,'{coupon}',2000)"
            )
            execute("UPDATE orders SET status='paid' WHERE id='one'")
            rejected(
                f"INSERT INTO orders VALUES ('two','member-a','pending',18000,'{coupon}',2000)"
            )
            rejected("UPDATE orders SET discount_krw=2001 WHERE id='one'")
            rejected("UPDATE orders SET discount_krw=-1 WHERE id='one'")
            execute("UPDATE orders SET status='canceled' WHERE id='one'")
            execute(f"INSERT INTO orders VALUES ('two','member-a','paid',9000,'{coupon}',1000)")
            rejected("UPDATE orders SET status='pending' WHERE id='one'")
            execute("INSERT INTO order_lines VALUES (2,'two',10000,1)")
            execute("DELETE FROM members WHERE id='member-a'")
            assert execute("SELECT count(*) FROM reward_attendance").scalar_one() == 0
            assert execute("SELECT count(*) FROM reward_coupons").scalar_one() == 0
            assert [
                tuple(r)
                for r in execute(
                    "SELECT id,amount_krw,reward_coupon_id,discount_krw FROM orders ORDER BY id"
                )
            ] == [("legacy", 12000, None, 0), ("one", 18000, None, 2000), ("two", 9000, None, 1000)]
            assert execute("SELECT count(*) FROM order_lines").scalar_one() == 2
            migration().downgrade()
            names = set(sa.inspect(conn).get_table_names(schema=schema))
            assert names == {"members", "orders", "order_lines"}
            assert [tuple(r) for r in execute("SELECT id,amount_krw FROM orders ORDER BY id")] == [
                ("legacy", 12000),
                ("one", 18000),
                ("two", 9000),
            ]

    async def run():
        engine = create_async_engine(os.environ["ATTENDANCE_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as conn:
                tx = await conn.begin()
                try:
                    await conn.run_sync(exercise)
                finally:
                    await tx.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("ATTENDANCE_MIGRATION_TEST_URL"), reason="needs test PostgreSQL"
)
@pytest.mark.parametrize("legacy_consent", [False, True], ids=["develop-0038", "ar-0038"])
def test_both_0038_schemas_reach_consent_and_rewards(legacy_consent):
    def exercise(conn):
        schema = "consent_test_" + uuid4().hex
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
        conn.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
        conn.exec_driver_sql("CREATE TABLE members (id varchar(64) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO members VALUES ('existing')")
        conn.exec_driver_sql("CREATE TABLE orders (id varchar(64) PRIMARY KEY, status varchar(20))")
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
        )
        scripts = ScriptDirectory.from_config(config)
        with EnvironmentContext(config, scripts) as env:
            env.configure(connection=conn)
            with Operations.context(env.get_context()):
                if legacy_consent:
                    conn.exec_driver_sql("ALTER TABLE members ADD camera_features_consent boolean")
                    conn.exec_driver_sql(
                        "ALTER TABLE members ADD ar_activity_consented_at timestamptz"
                    )
                    conn.exec_driver_sql("UPDATE members SET camera_features_consent = true")
                else:
                    scripts.get_revision("0038").module.upgrade()
                    conn.exec_driver_sql(
                        "INSERT INTO reward_attendance VALUES ('existing', CURRENT_DATE, 4)"
                    )
                scripts.get_revision("0039").module.upgrade()
                assert sa.inspect(conn).has_table("reward_coupons", schema=schema)
                assert conn.exec_driver_sql(
                    "SELECT camera_features_consent FROM members"
                ).scalar_one() is (True if legacy_consent else None)
                assert conn.exec_driver_sql(
                    "SELECT count(*) FROM reward_attendance"
                ).scalar_one() == (0 if legacy_consent else 1)

    async def run():
        engine = create_async_engine(os.environ["ATTENDANCE_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as conn:
                await conn.run_sync(exercise)
                # Schema, sample data and migration DDL are rolled back on connection close.
        finally:
            await engine.dispose()

    asyncio.run(run())
