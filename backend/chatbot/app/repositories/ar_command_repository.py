"""Process-local AR request deduplication for development only."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import lru_cache
from uuid import UUID

from app.core.errors import ApiError
from app.schemas.chat import ArAckRequest, ChatResponse


class MemoryArRequestRepository:
    """Keep completed and failed requests until restart; never silently evict IDs."""

    def __init__(self, limit: int = 1024) -> None:
        self._entries: dict[tuple[str, UUID], tuple[str, asyncio.Task[ChatResponse]]] = {}
        self._acks: dict[tuple[str, UUID], ArAckRequest] = {}
        self._limit = limit

    async def run(
        self,
        owner: str,
        request_id: UUID,
        fingerprint: str,
        factory: Callable[[], Awaitable[ChatResponse]],
    ) -> ChatResponse:
        key = (owner, request_id)
        entry = self._entries.get(key)
        if entry:
            if entry[0] != fingerprint:
                raise ApiError(
                    409, "Request ID already used for different content", "request_conflict"
                )
            task = entry[1]
        else:
            if len(self._entries) >= self._limit:
                raise ApiError(503, "AR request storage is full", "ar_requests_unavailable")
            # No await between lookup and insertion: one event loop creates only one task.
            task = asyncio.create_task(factory())
            self._entries[key] = (fingerprint, task)
        if task.done():
            return task.result()
        return await asyncio.shield(task)

    def record_ack(self, owner: str, ack: ArAckRequest) -> None:
        """Record only the first result for a proposal issued to this owner."""
        key = (owner, ack.request_id)
        entry = self._entries.get(key)
        if entry is None:
            raise ApiError(404, "AR proposal not found", "ar_proposal_not_found")
        task = entry[1]
        if not task.done():
            raise ApiError(409, "AR proposal is pending", "ar_proposal_pending")
        if task.cancelled() or task.exception() is not None:
            raise ApiError(404, "AR proposal not found", "ar_proposal_not_found")
        result = task.result()
        proposal = result.ar_result.action_proposal if result.ar_result else None
        if proposal is None or proposal.command_id != ack.command_id:
            raise ApiError(404, "AR proposal not found", "ar_proposal_not_found")
        existing = self._acks.get(key)
        if existing is not None and existing != ack:
            raise ApiError(409, "AR result already recorded", "ar_ack_conflict")
        if existing is None:
            # No await between the check and write: duplicate submissions are atomic per loop.
            self._acks[key] = ack.model_copy(deep=True)


@lru_cache
def get_ar_requests() -> MemoryArRequestRepository:
    return MemoryArRequestRepository()
