from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import AuthUser, require_user
from app.schemas.conversation import CreateConversationRequest, UpdateConversationStateRequest
from app.services.chat_service import ChatService, get_chat_service
from app.services.conversation_service import ConversationService

router = APIRouter(
    prefix="/api/chat/conversations", tags=["conversations"], dependencies=[Depends(require_user)]
)


@router.post("", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> dict:
    return await ConversationService(chat).create(user.id, body)


@router.get("")
async def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> dict:
    return await ConversationService(chat).list(user.id, limit, cursor)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> dict:
    return await ConversationService(chat).detail(user.id, conversation_id, limit, cursor)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> Response:
    await ConversationService(chat).delete(user.id, conversation_id)
    return Response(status_code=204)


@router.get("/{conversation_id}/requests/{request_id}")
async def get_request(
    conversation_id: UUID,
    request_id: UUID,
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> dict:
    return await ConversationService(chat).request_status(user.id, conversation_id, request_id)


@router.patch("/{conversation_id}/state")
async def update_state(
    conversation_id: UUID,
    body: UpdateConversationStateRequest,
    user: AuthUser = Depends(require_user),
    chat: ChatService = Depends(get_chat_service),
) -> dict:
    return await ConversationService(chat).update_state(user.id, conversation_id, body)
