import secrets
from collections import Counter

from app.core.errors import ApiError


class InventoryService:
    def __init__(self, repo):
        self.repo = repo

    async def check_quantities(self, quantities):
        for ident, quantity in sorted(quantities.items()):
            product = await self.repo.product(ident, lock=True)
            state = await self.repo.state(ident)
            if product is None or (state and not state.is_visible):
                raise ApiError(409, "Product is unavailable", "out_of_stock")
            if state and state.stock is not None and state.stock < quantity:
                raise ApiError(409, "Not enough stock", "out_of_stock")

    async def check_order(self, lines):
        quantities = Counter()
        for line in lines:
            quantities[line.product_id] += line.quantity
        await self.check_quantities(quantities)

    async def confirm(self, body, digest, approver):
        async with self.repo.transaction():
            await self.repo.catalog_lock()
            order = await self.repo.order(body.order_id, lock=True)
            if order is None or not secrets.compare_digest(order.checkout_token_hash, digest):
                raise ApiError(404, "Order not found", "not_found")
            if order.status in ("paid", "preparing", "shipped", "delivered"):
                if order.payment_key != body.payment_key or order.amount_krw != body.amount:
                    raise ApiError(400, "Payment does not match", "invalid_payment")
                return
            if order.status != "pending" or order.amount_krw != body.amount:
                raise ApiError(400, "Payment does not match", "invalid_payment")
            quantities = Counter()
            for line in order.lines:
                quantities[line.product_id] += line.quantity
            await self.check_quantities(quantities)
            # Locks stay held through approval. A retry uses the same provider idempotency key.
            await approver.approve(body.payment_key, order.id, body.amount)
            await self.repo.record_paid(order, body.payment_key, quantities)
