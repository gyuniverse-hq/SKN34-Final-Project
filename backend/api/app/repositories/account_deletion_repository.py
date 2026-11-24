"""Durable deletion job primitives; the caller controls transaction boundaries."""

import re
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_deletion import AccountDeletionJobRow

_NEXT_PHASE = {
    "BLOCKING": "PURGING_CHAT",
    "PURGING_CHAT": "DELETING_AUTH",
    "DELETING_AUTH": "DELETING_MEMBER",
    "DELETING_MEMBER": "DONE",
}
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class AccountDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_owner(self, owner_id: str) -> None:
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"g7:api:owner:{owner_id}", 0)))
        )

    async def is_installed(self) -> bool:
        return (
            await self._session.scalar(select(func.to_regclass("account_deletion_jobs")))
            is not None
        )

    async def has_jobs(self) -> bool:
        return await self._session.scalar(select(AccountDeletionJobRow.id).limit(1)) is not None

    async def status(self, owner_id: str) -> str | None:
        return await self._session.scalar(
            select(AccountDeletionJobRow.status).where(AccountDeletionJobRow.owner_id == owner_id)
        )

    async def get_or_create(self, owner_id: str) -> AccountDeletionJobRow:
        if not isinstance(owner_id, str) or not 1 <= len(owner_id) <= 64:
            raise ValueError("Invalid owner ID")
        await self._session.execute(
            insert(AccountDeletionJobRow)
            .values(id=uuid4(), owner_id=owner_id)
            .on_conflict_do_nothing(index_elements=[AccountDeletionJobRow.owner_id])
        )
        job = await self._session.scalar(
            select(AccountDeletionJobRow).where(AccountDeletionJobRow.owner_id == owner_id)
        )
        if job is None:
            raise RuntimeError("Deletion job could not be read")
        return job

    async def claim_next(self, lease_seconds: int) -> AccountDeletionJobRow | None:
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        now = func.clock_timestamp()
        job = await self._session.scalar(
            select(AccountDeletionJobRow)
            .where(
                or_(
                    and_(
                        AccountDeletionJobRow.status.in_(("PENDING", "RETRY_REQUIRED")),
                        AccountDeletionJobRow.next_attempt_at <= now,
                    ),
                    and_(
                        AccountDeletionJobRow.status == "IN_PROGRESS",
                        AccountDeletionJobRow.lease_until <= now,
                    ),
                )
            )
            .order_by(AccountDeletionJobRow.created_at, AccountDeletionJobRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "IN_PROGRESS"
        job.lease_token = uuid4()
        job.lease_until = now + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.updated_at = now
        await self._session.flush()
        await self._session.refresh(job)
        return job

    def _owned_job(self, job_id: UUID, lease_token: UUID, phase: str):
        return (
            AccountDeletionJobRow.id == job_id,
            AccountDeletionJobRow.status == "IN_PROGRESS",
            AccountDeletionJobRow.phase == phase,
            AccountDeletionJobRow.lease_token == lease_token,
            AccountDeletionJobRow.lease_until > func.clock_timestamp(),
        )

    async def advance(self, job_id: UUID, lease_token: UUID, phase: str) -> bool:
        next_phase = _NEXT_PHASE.get(phase)
        if next_phase is None:
            raise ValueError("Invalid deletion phase")
        values = {"phase": next_phase, "updated_at": func.clock_timestamp(), "error_code": None}
        if next_phase == "DONE":
            values.update(status="DONE", lease_token=None, lease_until=None)
        result = await self._session.scalar(
            update(AccountDeletionJobRow)
            .where(*self._owned_job(job_id, lease_token, phase))
            .values(**values)
            .returning(AccountDeletionJobRow.id)
        )
        return result is not None

    async def retry(
        self, job_id: UUID, lease_token: UUID, phase: str, error_code: str, delay_seconds: int
    ) -> bool:
        if phase not in _NEXT_PHASE or not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("Invalid deletion retry")
        if not 0 <= delay_seconds <= 86400:
            raise ValueError("Invalid retry delay")
        now = func.clock_timestamp()
        result = await self._session.scalar(
            update(AccountDeletionJobRow)
            .where(*self._owned_job(job_id, lease_token, phase))
            .values(
                status="RETRY_REQUIRED",
                lease_token=None,
                lease_until=None,
                next_attempt_at=now + timedelta(seconds=delay_seconds),
                error_code=error_code,
                updated_at=now,
            )
            .returning(AccountDeletionJobRow.id)
        )
        return result is not None
