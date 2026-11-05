from functools import lru_cache

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import get_settings


@lru_cache
def get_driver() -> AsyncDriver:
    s = get_settings()
    auth = (s.neo4j_user, s.neo4j_password) if s.neo4j_password else None
    return AsyncGraphDatabase.driver(s.neo4j_uri, auth=auth)


async def ping_graph() -> bool:
    try:
        await get_driver().verify_connectivity()
        return True
    except Exception:
        return False


async def close_driver() -> None:
    if get_driver.cache_info().currsize:
        await get_driver().close()
