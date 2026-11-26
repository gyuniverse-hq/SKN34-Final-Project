"""Opt-in vector migrations for databases provisioned with pgvector."""

import asyncio

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings


def migrate(connection):
    # Serialize with the ordinary schema migrations on the same database.
    connection.execute(text("SELECT pg_advisory_lock(7284731)"))
    connection.commit()
    try:
        context.configure(connection=connection, version_table="alembic_version_g5")
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(7284731)"))
        connection.commit()


async def run():
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        version_table="alembic_version_g5",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run())
