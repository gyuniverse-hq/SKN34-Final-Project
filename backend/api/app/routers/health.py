from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.cache import ping_redis
from app.core.db import ping_database

router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness: the process answers. No dependency checks, so a DB outage never restarts pods."""
    return {"ok": True}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness: take the pod out of the Service until PostgreSQL (and Redis, if set) respond."""
    database = await ping_database()
    redis = await ping_redis()
    ok = database and redis is not False
    return JSONResponse(
        {"ok": ok, "database": database, "redis": redis}, status_code=200 if ok else 503
    )
