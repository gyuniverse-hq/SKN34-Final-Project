from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.core.auth import AuthUser, require_user
from app.schemas.memory import (
    AccountMemorySettings,
    CreateMemoryRequest,
    DecideStructuredProposals,
    DeleteAllMemories,
    EditStructuredProposal,
    MemoryLocale,
    StructuredProposalGroup,
    StructuredProposalItem,
    UpdateAccountMemorySettings,
    UpdateMemoryRequest,
    UpdateStructuredMemory,
)
from app.services.memory_service import MemoryService
from app.services.memory_settings_service import MemorySettingsService
from app.services.structured_memory_service import StructuredMemoryService

router = APIRouter(prefix="/api/chat", tags=["memories"], dependencies=[Depends(require_user)])


@router.get("/memories")
async def list_memories(user: AuthUser = Depends(require_user)) -> dict:
    return await MemoryService().list(user.id)


@router.post("/memories")
async def create_memory(body: CreateMemoryRequest, user: AuthUser = Depends(require_user)) -> dict:
    return await MemoryService().create(user.id, body)


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: UUID, body: UpdateMemoryRequest, user: AuthUser = Depends(require_user)
) -> dict:
    return await MemoryService().update(user.id, memory_id, body)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    idempotency_key: Annotated[UUID, Header()],
    user: AuthUser = Depends(require_user),
) -> Response:
    await MemoryService().delete(user.id, memory_id, idempotency_key)
    return Response(status_code=204)


@router.get("/v2/memories")
async def list_structured_memories(
    locale: MemoryLocale = "en", user: AuthUser = Depends(require_user)
) -> dict:
    return await StructuredMemoryService().list_memories(user.id, locale)


@router.patch("/v2/memories/{memory_id}")
async def update_structured_memory(
    memory_id: UUID, body: UpdateStructuredMemory, user: AuthUser = Depends(require_user)
) -> dict:
    return await StructuredMemoryService().update_memory(user.id, memory_id, body)


@router.post("/v2/memories/delete-all")
async def delete_all_memories(
    body: DeleteAllMemories, user: AuthUser = Depends(require_user)
) -> AccountMemorySettings:
    return await MemorySettingsService().delete_all(user.id, body)


@router.get("/v2/memory-settings")
async def get_memory_settings(user: AuthUser = Depends(require_user)) -> AccountMemorySettings:
    return await MemorySettingsService().get(user.id)


@router.patch("/v2/memory-settings")
async def update_memory_settings(
    body: UpdateAccountMemorySettings, user: AuthUser = Depends(require_user)
) -> AccountMemorySettings:
    return await MemorySettingsService().update(user.id, body)


@router.delete("/v2/memories/{memory_id}", status_code=204)
async def delete_structured_memory(
    memory_id: UUID,
    idempotency_key: Annotated[UUID, Header()],
    user: AuthUser = Depends(require_user),
) -> Response:
    await MemoryService().delete(user.id, memory_id, idempotency_key, schema_version=2)
    return Response(status_code=204)


@router.get("/v2/memory-proposals")
async def list_structured_proposals(
    conversation_id: Annotated[UUID, Query(alias="conversationId")],
    user: AuthUser = Depends(require_user),
) -> list[StructuredProposalGroup]:
    return await StructuredMemoryService().list_groups(user.id, conversation_id)


@router.patch("/v2/memory-proposals/{group_id}/{item_id}")
async def edit_structured_proposal(
    group_id: UUID,
    item_id: UUID,
    body: EditStructuredProposal,
    user: AuthUser = Depends(require_user),
) -> StructuredProposalItem:
    return await StructuredMemoryService().edit(user.id, group_id, item_id, body)


@router.post("/v2/memory-proposals/{group_id}/decisions")
async def decide_structured_proposal(
    group_id: UUID, body: DecideStructuredProposals, user: AuthUser = Depends(require_user)
) -> dict:
    return await StructuredMemoryService().decide(user.id, group_id, body)
