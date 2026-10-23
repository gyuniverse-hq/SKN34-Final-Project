from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, require_user
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter, get_rate_limiter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: AuthUser = Depends(require_user),
    limiter: RateLimiter = Depends(get_rate_limiter),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    if not await limiter.allow(user.id):
        raise ApiError(429, "Too many questions. Please wait a moment.", "rate_limited")
    return await service.answer(body)
