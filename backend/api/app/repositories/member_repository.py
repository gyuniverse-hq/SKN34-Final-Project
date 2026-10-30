from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import MemberRow
from app.schemas.member import MemberRecord


def _record(row: MemberRow) -> MemberRecord:
    return MemberRecord(
        id=row.id, terms_version=row.terms_version, terms_agreed_at=row.terms_agreed_at
    )


class MemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, member_id: str) -> MemberRecord | None:
        row = await self._session.scalar(select(MemberRow).where(MemberRow.id == member_id))
        return _record(row) if row else None

    async def save_terms(self, member_id: str, version: str, agreed_at: datetime) -> MemberRecord:
        values = {"terms_version": version, "terms_agreed_at": agreed_at}
        stmt = (
            insert(MemberRow)
            .values(id=member_id, **values)
            .on_conflict_do_update(index_elements=[MemberRow.id], set_=values)
            .returning(MemberRow)
            .execution_options(populate_existing=True)
        )
        row = await self._session.scalar(stmt)
        await self._session.commit()
        return _record(row)

    async def delete(self, member_id: str) -> None:
        await self._session.execute(delete(MemberRow).where(MemberRow.id == member_id))
        await self._session.commit()
