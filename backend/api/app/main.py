import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.observability import RequestContextMiddleware, configure_logging
from app.routers import (
    catalog,
    celebrity_videos,
    health,
    idol_looks,
    members,
    payments,
    recommendation_comparison,
    recommendations,
    shades,
    style_looks,
    tutorials,
)
from app.services.skincare_refresh_service import run_refresh_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    enabled = settings.skincare_refresh_enabled
    if enabled is None:
        enabled = not settings.is_production
    task = asyncio.create_task(run_refresh_loop()) if enabled else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
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
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for module in (
        health,
        catalog,
        idol_looks,
        shades,
        members,
        tutorials,
        style_looks,
        celebrity_videos,
        recommendations,
        recommendation_comparison,
    ):
        app.include_router(module.router)
    app.include_router(payments.router)
    app.include_router(payments.api)
    return app


app = create_app()
