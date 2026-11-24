from fastapi import APIRouter, Depends

from app.core.auth import ChatPrincipal, chat_principal
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter, get_rate_limiter
from app.schemas.chat import ArAckRequest, ArAckResponse, ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from app.services.conversation_service import ConversationService
from app.services.owner_deletion_service import OwnerDeletionService

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    principal: ChatPrincipal = Depends(chat_principal),
    limiter: RateLimiter = Depends(get_rate_limiter),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    if body.conversation_id is not None and principal.user is None:
        raise ApiError(403, "Sign in required for persistent chat", "persistent_login_required")
    owner_id = principal.user.id if principal.user else None
    async with OwnerDeletionService.access(owner_id):
        if not await limiter.allow(principal.rate_limit_key):
            raise ApiError(429, "Too many questions. Please wait a moment.", "rate_limited")
    if body.conversation_id is not None:
        return await ConversationService(service).answer(
            principal.user.id, principal.rate_limit_key, body
        )
    response = await service.answer(body, principal.rate_limit_key)
    async with OwnerDeletionService.access(owner_id):
        return response


@router.post("/chat/acks", response_model=ArAckResponse)
async def acknowledge_ar(
    body: ArAckRequest,
    principal: ChatPrincipal = Depends(chat_principal),
    service: ChatService = Depends(get_chat_service),
) -> ArAckResponse:
    owner_id = principal.user.id if principal.user else None
    async with OwnerDeletionService.access(owner_id):
        service.acknowledge_ar(principal.rate_limit_key, body)
        return ArAckResponse(received=True)
