from datetime import datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.member import MemberRow
from app.repositories.account_deletion_repository import AccountDeletionRepository
from app.schemas.member import MemberRecord


def _record(row: MemberRow) -> MemberRecord:
    return MemberRecord(
        id=row.id,
        terms_version=row.terms_version,
        terms_agreed_at=row.terms_agreed_at,
        skin_trial_run=row.skin_trial_run,
        skin_subscription_until=row.skin_subscription_until,
    )


class MemberRepository:
    def __init__(self, session: AsyncSession, *, guard_deletion: bool = False) -> None:
        self._session = session
        self._guard_deletion = guard_deletion

    async def require_available(self, member_id: str, *, write: bool = False) -> None:
        if not self._guard_deletion:
            return
        jobs = AccountDeletionRepository(self._session)
        try:
            if write:
                await jobs.lock_owner(member_id)
            if not get_settings().g7_account_deletion_enabled and not await jobs.is_installed():
                return
            status = await jobs.status(member_id)
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(
                503, "Member status is unavailable", "account_deletion_unavailable"
            ) from exc
        if status is not None:
            raise ApiError(403, "Account is unavailable", "account_unavailable")

    async def get(self, member_id: str) -> MemberRecord | None:
        await self.require_available(member_id)
        row = await self._session.scalar(select(MemberRow).where(MemberRow.id == member_id))
        return _record(row) if row else None

    async def save_terms(self, member_id: str, version: str, agreed_at: datetime) -> MemberRecord:
        await self.require_available(member_id, write=True)
        values = {"terms_version": version, "terms_agreed_at": agreed_at}
        stmt = (
            insert(MemberRow)
            .values(id=member_id, **values)
            .on_conflict_do_update(
                index_elements=[MemberRow.id],
                set_={
                    **values,
                    "terms_agreed_at": case(
                        (MemberRow.terms_version == version, MemberRow.terms_agreed_at),
                        else_=agreed_at,
                    ),
                },
            )
            .returning(MemberRow)
            .execution_options(populate_existing=True)
        )
        row = await self._session.scalar(stmt)
        await self._session.commit()
        return _record(row)

    async def claim_first_ar_visit(self, member_id: str) -> bool:
        await self.require_available(member_id, write=True)
        stmt = (
            update(MemberRow)
            .where(MemberRow.id == member_id, MemberRow.first_ar_seen_at.is_(None))
            .values(first_ar_seen_at=func.now())
            .returning(MemberRow.skin_trial_run.is_(None))
        )
        eligible = await self._session.scalar(stmt)
        await self._session.commit()
        return bool(eligible)

    async def complete_analysis(self, member_id: str, run_id: str) -> MemberRecord | None:
        await self.require_available(member_id, write=True)
        stmt = (
            update(MemberRow)
            .where(
                MemberRow.id == member_id,
                or_(
                    MemberRow.skin_trial_run.is_(None),
                    MemberRow.skin_trial_run == run_id,
                    MemberRow.skin_subscription_until > func.now(),
                ),
            )
            .values(skin_trial_run=func.coalesce(MemberRow.skin_trial_run, run_id))
            .returning(MemberRow)
            .execution_options(populate_existing=True)
        )
        row = await self._session.scalar(stmt)
        record = _record(row) if row else None
        await self._session.commit()
        return record

    async def set_skin_subscription(self, member_id: str, until: datetime) -> MemberRecord | None:
        await self.require_available(member_id, write=True)
        stmt = (
            update(MemberRow)
            .where(MemberRow.id == member_id)
            .values(skin_subscription_until=until)
            .returning(MemberRow)
            .execution_options(populate_existing=True)
        )
        row = await self._session.scalar(stmt)
        record = _record(row) if row else None
        await self._session.commit()
        return record

    async def delete(self, member_id: str) -> None:
        await self._session.execute(delete(MemberRow).where(MemberRow.id == member_id))
        await self._session.commit()
