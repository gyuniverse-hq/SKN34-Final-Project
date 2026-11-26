from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import dispose_chat_engine
from app.core.errors import install_error_handlers
from app.core.graph import close_driver
from app.core.observability import RequestContextMiddleware, configure_logging
from app.core.ratelimit import close_redis
from app.routers import chat, conversations, health, internal_account_deletion, memories


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_driver()
    await close_redis()
    await dispose_chat_engine()


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
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Request-ID",
                "X-Vishue-Anonymous-Id",
            ],
        )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(memories.router)
    if settings.env in {"local", "test"} and settings.g7_internal_deletion_enabled:
        app.include_router(internal_account_deletion.router)
    return app


app = create_app()
