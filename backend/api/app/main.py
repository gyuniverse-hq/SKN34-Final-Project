from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.observability import RequestContextMiddleware, configure_logging
from app.routers import catalog, health, members, shades, tutorials


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("api", settings.log_level)
    docs = not settings.is_production
    app = FastAPI(
        title="VISHUE API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/openapi.json" if docs else None,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for module in (health, catalog, shades, members, tutorials):
        app.include_router(module.router)
    return app


app = create_app()
