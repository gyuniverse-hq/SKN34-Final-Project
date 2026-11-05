from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.graph import ping_graph
from app.core.ratelimit import ping_redis

router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    """Liveness: the process answers. No dependency checks, so a DB outage never restarts pods."""
    return {"ok": True}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness: take the pod out of the Service until Neo4j (and Redis, if set) respond."""
    graph = await ping_graph()
    redis = await ping_redis()
    ok = graph and redis is not False
    return JSONResponse({"ok": ok, "graph": graph, "redis": redis}, status_code=200 if ok else 503)
