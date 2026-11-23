from datetime import UTC, datetime
from uuid import uuid4

from app.models.member import MemberRow
from app.models.recommendation_feedback import UserBehaviorEventRow
from app.repositories.admin_repository import AdminRepository


class InventoryRepository(AdminRepository):
    async def record_paid(self, order, payment_key, quantities):
        for line in order.lines:
            state = await self.state(line.product_id)
            line.stock_debited = line.quantity if state and state.stock is not None else 0
        for ident, quantity in quantities.items():
            state = await self.state(ident)
            if state and state.stock is not None:
                state.stock -= quantity
                state.updated_at, state.updated_by = datetime.now(UTC), None
        order.status, order.payment_key, order.paid_at = "paid", payment_key, datetime.now(UTC)
        member = await self.session.get(MemberRow, order.user_id)
        for line in order.lines:
            self.session.add(
                UserBehaviorEventRow(
                    event_id=uuid4(),
                    member_id=member.id if member else None,
                    session_id=uuid4(),
                    order_line_id=line.id,
                    product_id=line.product_id,
                    option_id=None,
                    event_type="purchase_confirmed",
                    event_source="server",
                    occurred_at=order.paid_at,
                    source_record_key=f"purchase:{line.id}",
                    event_schema_version="admin-commerce-v1",
                    surface="checkout",
                    context_snapshot={"quantity": line.quantity},
                )
            )
