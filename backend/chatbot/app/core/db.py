from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_chat_engine() -> AsyncEngine:
    url = get_settings().chat_database_url
    if not url:
        raise RuntimeError("CHAT_DATABASE_URL is not configured")
    return create_async_engine(url, pool_pre_ping=True)


async def get_chat_session() -> AsyncIterator[AsyncSession]:
    factory = get_chat_sessionmaker()
    async with factory() as session:
        yield session


def get_chat_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_chat_engine(), expire_on_commit=False)


async def dispose_chat_engine() -> None:
    if get_chat_engine.cache_info().currsize:
        await get_chat_engine().dispose()
        get_chat_engine.cache_clear()
