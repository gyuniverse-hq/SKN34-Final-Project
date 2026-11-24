from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import LipEvalProductRow, LipEvalSlotRow
from app.repositories.admin_repository import AdminRepository


class LipEvalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.admin = AdminRepository(session)

    async def products(self) -> list[LipEvalProductRow]:
        result = await self.session.scalars(
            select(LipEvalProductRow).order_by(LipEvalProductRow.sort_order)
        )
        return list(result)

    async def product(self, product_id: str) -> LipEvalProductRow | None:
        return await self.session.get(LipEvalProductRow, product_id)

    async def slots_for(self, product_id: str) -> list[LipEvalSlotRow]:
        result = await self.session.scalars(
            select(LipEvalSlotRow)
            .where(LipEvalSlotRow.product_id == product_id)
            .order_by(LipEvalSlotRow.rater_id)
        )
        return list(result)

    async def all_slots(self) -> list[LipEvalSlotRow]:
        result = await self.session.scalars(select(LipEvalSlotRow))
        return list(result)

    async def slot(self, product_id: str, rater_id: int) -> LipEvalSlotRow | None:
        return await self.session.get(LipEvalSlotRow, (product_id, rater_id))

    async def upsert_slot(self, row: LipEvalSlotRow) -> LipEvalSlotRow:
        row.updated_at = datetime.now(UTC)
        merged = await self.session.merge(row)
        await self.session.flush()
        return merged

    def audit(
        self,
        actor: str,
        action: str,
        target_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        request_id: str,
    ) -> None:
        self.admin.audit(actor, action, "lip_eval_slot", target_id, before, after, request_id)

    def transaction(self):
        return self.admin.transaction()
