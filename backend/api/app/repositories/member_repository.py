from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import MemberRow
from app.schemas.member import ConsentKind, MemberRecord


def _record(row: MemberRow) -> MemberRecord:
    return MemberRecord(
        id=row.id,
        terms_version=row.terms_version,
        terms_agreed_at=row.terms_agreed_at,
        camera_features_consent=row.camera_features_consent,
        ar_activity_consented_at=row.ar_activity_consented_at,
        skin_trial_run=row.skin_trial_run,
        skin_subscription_until=row.skin_subscription_until,
    )


class MemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, member_id: str) -> MemberRecord | None:
        row = await self._session.scalar(select(MemberRow).where(MemberRow.id == member_id))
        return _record(row) if row else None

    async def save_terms(
        self,
        member_id: str,
        version: str,
        agreed_at: datetime,
        ar_consent: bool | None = None,
        camera_consent: bool | None = None,
    ) -> MemberRecord:
        values = {"terms_version": version, "terms_agreed_at": agreed_at}
        if camera_consent is not None:
            values["camera_features_consent"] = camera_consent
        if ar_consent is not None:
            values["ar_activity_consented_at"] = agreed_at if ar_consent else None
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

    async def set_consent(
        self, member_id: str, kind: ConsentKind, enabled: bool
    ) -> MemberRecord | None:
        stmt = (
            update(MemberRow)
            .where(MemberRow.id == member_id)
            .values(
                {"camera_features_consent": enabled}
                if kind == "cameraFeatures"
                else {"ar_activity_consented_at": func.now() if enabled else None}
            )
            .returning(MemberRow)
            .execution_options(populate_existing=True)
        )
        row = await self._session.scalar(stmt)
        record = _record(row) if row else None
        await self._session.commit()
        return record

    async def claim_first_ar_visit(self, member_id: str) -> bool:
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
