from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response

from app.core.auth import AuthUser, require_user
from app.schemas.memory import CreateMemoryRequest, UpdateMemoryRequest
from app.services.memory_service import MemoryService

router = APIRouter(
    prefix="/api/chat/memories", tags=["memories"], dependencies=[Depends(require_user)]
)


@router.get("")
async def list_memories(user: AuthUser = Depends(require_user)) -> dict:
    return await MemoryService().list(user.id)


@router.post("")
async def create_memory(body: CreateMemoryRequest, user: AuthUser = Depends(require_user)) -> dict:
    return await MemoryService().create(user.id, body)


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: UUID, body: UpdateMemoryRequest, user: AuthUser = Depends(require_user)
) -> dict:
    return await MemoryService().update(user.id, memory_id, body)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    idempotency_key: Annotated[UUID, Header()],
    user: AuthUser = Depends(require_user),
) -> Response:
    await MemoryService().delete(user.id, memory_id, idempotency_key)
    return Response(status_code=204)
