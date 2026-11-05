from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import OrderLineRow, OrderRow


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, order: OrderRow) -> None:
        self._session.add(order)
        await self._session.commit()

    async def get(self, order_id: str) -> OrderRow | None:
        return await self._session.scalar(select(OrderRow).where(OrderRow.id == order_id))

    async def mark_paid(self, order: OrderRow, payment_key: str) -> None:
        order.status = "paid"
        order.payment_key = payment_key
        await self._session.commit()

    @staticmethod
    def line(**values: object) -> OrderLineRow:
        return OrderLineRow(**values)
