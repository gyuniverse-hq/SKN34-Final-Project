from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.graph import close_driver
from app.core.observability import RequestContextMiddleware, configure_logging
from app.core.ratelimit import close_redis
from app.routers import chat, health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_driver()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("chatbot", settings.log_level)
    docs = not settings.is_production
    app = FastAPI(
        title="VISHUE Chatbot",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/chat/openapi.json" if docs else None,
        docs_url="/api/chat/docs" if docs else None,
        redoc_url=None,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["POST"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()
