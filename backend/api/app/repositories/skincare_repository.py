from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.skincare import SkincareServingRow
from app.schemas.skincare import SkincareSnapshot


class SkincareRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read(self) -> SkincareSnapshot | None:
        row = await self.session.get(SkincareServingRow, 1)
        return SkincareSnapshot.model_validate(row.payload) if row else None

    async def publish(self, snapshot: SkincareSnapshot):
        payload = snapshot.model_dump(mode="json", by_alias=True)
        async with self.session.begin():
            stmt = insert(SkincareServingRow).values(
                id=1, data_version=snapshot.data_version, payload=payload
            )
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={"data_version": snapshot.data_version, "payload": payload},
                )
            )


def get_skincare_repository(session: AsyncSession = Depends(get_session)):
    return SkincareRepository(session)
