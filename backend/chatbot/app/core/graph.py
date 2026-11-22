from functools import lru_cache

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import get_settings


@lru_cache
def get_driver() -> AsyncDriver:
    s = get_settings()
    auth = (s.neo4j_user, s.neo4j_password) if s.neo4j_password else None
    return AsyncGraphDatabase.driver(s.neo4j_uri, auth=auth)


async def ping_graph() -> bool:
    # ADR-0012: Neo4j is retired; skip the graph check when no password is configured
    # so readiness does not block the pod during the pgvector cutover.
    if not get_settings().neo4j_password:
        return True
    try:
        await get_driver().verify_connectivity()
        return True
    except Exception:
        return False



async def close_driver() -> None:
    if get_driver.cache_info().currsize:
        await get_driver().close()
