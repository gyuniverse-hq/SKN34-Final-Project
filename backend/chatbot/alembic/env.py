import asyncio

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.core.db import Base

config = context.config
target_metadata = Base.metadata
MIGRATION_LOCK_ID = 7_284_732
url = get_settings().chat_database_url
if not url:
    raise RuntimeError("CHAT_DATABASE_URL is required for chatbot migrations")


def include_object(obj, name, type_, reflected, compare_to):
    # LangGraph owns and migrates these tables independently of Alembic.
    if type_ == "table" and reflected and compare_to is None:
        return name not in {
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
            "checkpoint_migrations",
        }
    return True


def migrate(connection):
    connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
    connection.commit()
    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
        connection.commit()


async def migrate_async():
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(migrate_async())
