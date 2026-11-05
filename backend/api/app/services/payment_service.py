import hashlib
import secrets
from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.toss_client import PaymentApprover, TossPaymentsClient
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models.order import OrderRow
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.payment import (
    ConfirmPaymentRequest,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderStatus,
    PaymentResult,
    PublicCheckout,
)


class CatalogStore(Protocol):
    async def get_product(self, product_id: str): ...


class OrderStore(Protocol):
    async def create(self, order: OrderRow) -> None: ...
    async def get(self, order_id: str) -> OrderRow | None: ...
    async def mark_paid(self, order: OrderRow, payment_key: str) -> None: ...
    def line(self, **values: object): ...


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PaymentService:
    def __init__(
        self,
        orders: OrderStore,
        catalog: CatalogStore,
        approver: PaymentApprover,
        settings: Settings,
    ) -> None:
        self._orders, self._catalog, self._approver, self._settings = (
            orders,
            catalog,
            approver,
            settings,
        )

    async def create_order(self, user_id: str, body: CreateOrderRequest) -> CreateOrderResponse:
        if not (self._settings.toss_client_key and self._settings.payment_web_base_url):
            raise ApiError(503, "Payments are not configured", "payment_unavailable")
        lines, total = [], 0
        for request_line in body.lines:
            product = await self._catalog.get_product(request_line.product_id)
            if product is None or (
                request_line.shade_id
                and not any(s.id == request_line.shade_id for s in product.shades)
            ):
                raise ApiError(400, "An item is no longer available", "invalid_order")
            lines.append(
                self._orders.line(
                    product_id=product.id,
                    shade_id=request_line.shade_id,
                    quantity=request_line.quantity,
                    unit_price_krw=product.price_krw,
                )
            )
            total += product.price_krw * request_line.quantity
        order_id, token = f"O{secrets.token_urlsafe(24)}", secrets.token_urlsafe(32)
        name = (
            f"{lines[0].product_id} 외 {len(lines) - 1}건"
            if len(lines) > 1
            else lines[0].product_id
        )
        await self._orders.create(
            OrderRow(
                id=order_id,
                user_id=user_id,
                amount_krw=total,
                order_name=name,
                status="pending",
                checkout_token_hash=_digest(token),
                payment_key=None,
                lines=lines,
            )
        )
        base = self._settings.payment_web_base_url.rstrip("/")
        return CreateOrderResponse(
            orderId=order_id, amount=total, checkoutUrl=f"{base}/pay/{order_id}?token={token}"
        )

    async def checkout(self, order_id: str, token: str) -> PublicCheckout:
        order = await self._orders.get(order_id)
        if (
            order is None
            or not secrets.compare_digest(order.checkout_token_hash, _digest(token))
            or order.status != "pending"
        ):
            raise ApiError(404, "Checkout is unavailable", "not_found")
        return PublicCheckout(
            order_id=order.id,
            order_name=order.order_name,
            amount=order.amount_krw,
            checkout_token=token,
        )

    async def order_status(self, user_id: str, order_id: str) -> OrderStatus:
        order = await self._orders.get(order_id)
        if order is None or order.user_id != user_id:
            raise ApiError(404, "Order was not found", "not_found")
        return OrderStatus(orderId=order.id, status=order.status)

    async def confirm(self, body: ConfirmPaymentRequest) -> PaymentResult:
        order = await self._orders.get(body.order_id)
        if order is None or not secrets.compare_digest(
            order.checkout_token_hash, _digest(body.checkout_token)
        ):
            raise ApiError(404, "Order was not found", "not_found")
        if order.status == "paid":
            return PaymentResult(
                orderId=order.id, status="paid", returnUrl=self._settings.payment_return_url
            )
        if order.status != "pending" or order.amount_krw != body.amount:
            raise ApiError(400, "Payment amount does not match the order", "invalid_payment")
        await self._approver.approve(body.payment_key, order.id, body.amount)
        await self._orders.mark_paid(order, body.payment_key)
        return PaymentResult(
            orderId=order.id, status="paid", returnUrl=self._settings.payment_return_url
        )


def get_payment_service(session: AsyncSession = Depends(get_session)) -> PaymentService:
    settings = get_settings()
    return PaymentService(
        OrderRepository(session),
        CatalogRepository(session),
        TossPaymentsClient(settings.toss_secret_key),
        settings,
    )
