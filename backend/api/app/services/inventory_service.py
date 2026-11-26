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

    async def lock_catalog(self):
        await self.repo.catalog_lock()

    async def record_paid(self, order, payment_key):
        quantities = Counter()
        for line in order.lines:
            quantities[line.product_id] += line.quantity
        await self.repo.record_paid(order, payment_key, quantities)
