from fastapi import APIRouter, Depends

from app.core.auth import ChatPrincipal, chat_principal
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter, get_rate_limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    principal: ChatPrincipal = Depends(chat_principal),
    limiter: RateLimiter = Depends(get_rate_limiter),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    if not await limiter.allow(principal.rate_limit_key):
        raise ApiError(429, "Too many questions. Please wait a moment.", "rate_limited")
    return await service.answer(body)
