"""Verify account-scoped memory changes and keep policy fences with the same commit."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import ApiError
from app.models.conversation import ChatOwnerStatus
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import AccountMemorySettings, DeleteAllMemories, UpdateAccountMemorySettings
from app.services.memory_service import MemoryService, _fingerprint


def _changed() -> ApiError:
    return ApiError(409, "Review the current memory settings", "memory_settings_changed")


def _advance(owner: ChatOwnerStatus) -> None:
    if owner.memory_policy_version >= 2**53 - 1:
        raise _changed()
    owner.memory_policy_version += 1


@asynccontextmanager
async def _locked_account(owner_id: str) -> AsyncIterator[tuple[MemoryRepository, ChatOwnerStatus]]:
    try:
        async with MemoryService._sessions().begin() as session:
            if not await ConversationRepository(session).ensure_active_owner(owner_id):
                raise ApiError(403, "Account is unavailable", "account_unavailable")
            repo = MemoryRepository(session)
            owner = await repo.owner_settings(owner_id)
            if owner is None:
                raise ApiError(403, "Account is unavailable", "account_unavailable")
            yield repo, owner
    except (SQLAlchemyError, OSError) as exc:
        raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc


async def _snapshot(repo: MemoryRepository, owner: ChatOwnerStatus) -> AccountMemorySettings:
    return AccountMemorySettings(
        enabled=owner.memory_enabled,
        version=owner.memory_policy_version,
        notice_acknowledged=owner.memory_notice_at is not None,
        memory_set_revision=await repo.generation(owner.owner_id, True),
    )


class MemorySettingsService:
    async def get(self, owner_id: str) -> AccountMemorySettings:
        async with _locked_account(owner_id) as (repo, owner):
            return await _snapshot(repo, owner)

    async def update(
        self, owner_id: str, body: UpdateAccountMemorySettings
    ) -> AccountMemorySettings:
        operation = "memory_settings_update"
        fingerprint = _fingerprint(owner_id, operation, body.model_dump(mode="json"))
        async with _locked_account(owner_id) as (repo, owner):
            if await MemoryService._previous(
                repo.session, owner_id, body.request_id, operation, fingerprint
            ):
                return await _snapshot(repo, owner)
            if owner.memory_policy_version != body.expected_version:
                raise _changed()
            now = datetime.now(UTC)
            changing_mode = body.enabled is not None and body.enabled != owner.memory_enabled
            acknowledging = body.acknowledge_notice is True and owner.memory_notice_at is None
            if changing_mode or acknowledging:
                owner.updated_at = now
            if changing_mode:
                _advance(owner)
                owner.memory_enabled = body.enabled
                owner.revocation_epoch += 1
                await repo.clear_pending(owner_id)
            if acknowledging:
                owner.memory_notice_at = now
            MemoryService._record(
                repo.session, owner_id, body.request_id, operation, fingerprint, None, None
            )
            return await _snapshot(repo, owner)

    async def delete_all(self, owner_id: str, body: DeleteAllMemories) -> AccountMemorySettings:
        operation = "memory_delete_all"
        fingerprint = _fingerprint(owner_id, operation, body.model_dump(mode="json"))
        async with _locked_account(owner_id) as (repo, owner):
            if await MemoryService._previous(
                repo.session, owner_id, body.request_id, operation, fingerprint
            ):
                return await _snapshot(repo, owner)
            revision = await repo.generation(owner_id, True)
            if (
                owner.memory_policy_version != body.expected_version
                or revision != body.expected_memory_set_revision
            ):
                raise _changed()
            _advance(owner)
            owner.revocation_epoch += 1
            owner.updated_at = datetime.now(UTC)
            await repo.clear_pending(owner_id)
            await repo.clear_approved(owner_id)
            MemoryService._record(
                repo.session, owner_id, body.request_id, operation, fingerprint, None, None
            )
            return await _snapshot(repo, owner)
