import hashlib
import secrets
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.toss_client import PaymentApprover, TossPaymentsClient
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.models.order import OrderRow
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.reward_repository import RewardRepository
from app.schemas.payment import (
    ConfirmPaymentRequest,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderStatus,
    PaymentResult,
    PublicCheckout,
)
from app.services.inventory_service import InventoryService
from app.services.member_service import TERMS_VERSION
from app.services.reward_service import RewardService


class CatalogStore(Protocol):
    async def get_product(self, product_id: str): ...


class OrderStore(Protocol):
    async def create(
        self,
        order: OrderRow,
        *,
        ar_cart_events: list[list[UUID]],
        ar_terms: str | None,
        skincare_cart_events: list[list[UUID]],
        cart_visit_id: UUID | None = None,
        cart_recommendation_events: list[list[UUID]] | None = None,
    ) -> None: ...
    async def get(self, order_id: str, *, lock: bool = False) -> OrderRow | None: ...
    async def mark_paid(
        self, order: OrderRow, payment_key: str, *, ar_terms: str | None, skincare_feedback: bool
    ) -> None: ...
    async def commit(self) -> None: ...
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
        inventory: InventoryService | None = None,
        rewards: RewardService | None = None,
    ) -> None:
        self._orders, self._catalog, self._approver, self._settings = (
            orders,
            catalog,
            approver,
            settings,
        )
        self._inventory = inventory
        self._rewards = rewards

    def _skincare_feedback(self, user_id: str) -> bool:
        return user_id in self._settings.skin_recommendation_feedback_consented_members

    async def create_order(self, user_id: str, body: CreateOrderRequest) -> CreateOrderResponse:
        if not (self._settings.toss_client_key and self._settings.payment_web_base_url):
            raise ApiError(503, "Payments are not configured", "payment_unavailable")
        lines, total = [], 0
        if self._inventory:
            await self._inventory.check_order(body.lines)
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
        discount = 0
        if body.coupon_id:
            if not self._rewards:
                raise ApiError(503, "Coupon service is unavailable", "coupon_unavailable")
            discount = await self._rewards.discount(user_id, body.coupon_id, total)
        order_id, token = f"O{secrets.token_urlsafe(24)}", secrets.token_urlsafe(32)
        name = (
            f"{lines[0].product_id} 외 {len(lines) - 1}건"
            if len(lines) > 1
            else lines[0].product_id
        )
        cart_feedback = (
            {
                "cart_visit_id": body.cart_visit_id,
                "cart_recommendation_events": [
                    line.cart_recommendation_event_ids[: line.quantity] for line in body.lines
                ],
            }
            if body.cart_visit_id and self._settings.cart_recommendation_experiment
            else {}
        )
        await self._orders.create(
            OrderRow(
                id=order_id,
                user_id=user_id,
                amount_krw=total - discount,
                discount_krw=discount,
                reward_coupon_id=body.coupon_id,
                order_name=name,
                status="pending",
                checkout_token_hash=_digest(token),
                payment_key=None,
                lines=lines,
            ),
            ar_cart_events=[line.ar_cart_event_ids[: line.quantity] for line in body.lines],
            ar_terms=TERMS_VERSION,
            skincare_cart_events=[
                line.skincare_cart_event_ids[: line.quantity] for line in body.lines
            ]
            if self._skincare_feedback(user_id)
            else [],
            **cart_feedback,
        )
        base = self._settings.payment_web_base_url.rstrip("/")
        path = f"/pay/{order_id}?token={token}"
        local_test = self._settings.env in {"local", "development", "test"} and (
            self._settings.toss_secret_key or ""
        ).startswith("test_")
        return CreateOrderResponse(
            orderId=order_id,
            amount=total - discount,
            checkoutUrl=base + path,
            localCheckoutPath=path if local_test else None,
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
        # Mobile checkout treats only `paid` as success; fulfillment is an admin concern.
        payment_status = (
            "paid"
            if order.status in ("paid", "preparing", "shipped", "delivered")
            else order.status
        )
        return OrderStatus(orderId=order.id, status=payment_status)

    async def _locked_order(self, order_id: str):
        if self._inventory:
            await self._inventory.lock_catalog()
        return await self._orders.get(order_id, lock=True)

    async def _record_paid(self, order, payment_key):
        if self._inventory:
            await self._inventory.record_paid(order, payment_key)
            await self._orders.commit()
        else:
            await self._orders.mark_paid(
                order,
                payment_key,
                ar_terms=TERMS_VERSION,
                skincare_feedback=self._skincare_feedback(order.user_id),
            )

    async def close_checkout(self, user_id: str, order_id: str) -> OrderStatus:
        order = await self._locked_order(order_id)
        if order is None or order.user_id != user_id:
            raise ApiError(404, "Order was not found", "not_found")
        if order.status == "pending" and order.discount_krw:
            if not order.payment_key:
                # No approval has started. Closing the order also invalidates its checkout URL.
                order.status = "canceled"
                await self._orders.commit()
            else:
                state = await self._approver.lookup(order.payment_key, order.id, order.amount_krw)
                if state in {"CANCELED", "EXPIRED", "ABORTED"}:
                    order.status = "canceled"
                    await self._orders.commit()
                elif state == "DONE":
                    if self._inventory:
                        await self._inventory.check_order(order.lines)
                    await self._record_paid(order, order.payment_key)
        return await self.order_status(user_id, order_id)

    async def confirm(self, body: ConfirmPaymentRequest) -> PaymentResult:
        digest = _digest(body.checkout_token)
        order = await self._locked_order(body.order_id)
        if order is None or not secrets.compare_digest(order.checkout_token_hash, digest):
            raise ApiError(404, "Order was not found", "not_found")
        if order.amount_krw != body.amount or (
            order.payment_key and order.payment_key != body.payment_key
        ):
            raise ApiError(400, "Payment does not match this order", "invalid_payment")
        result = PaymentResult(
            orderId=order.id, status="paid", returnUrl=self._settings.payment_return_url
        )
        if order.status in {"paid", "preparing", "shipped", "delivered"}:
            return result
        if order.status != "pending":
            raise ApiError(409, "Checkout has closed", "invalid_payment")

        if order.discount_krw and not order.payment_key:
            await self._validate_coupon(order)
            if self._inventory:
                await self._inventory.check_order(order.lines)
            # Persist the attempt before contacting Toss. A timeout or crash must leave
            # a key the owner can reconcile, even if the local paid transaction rolls back.
            order.payment_key = body.payment_key
            await self._orders.commit()
            order = await self._locked_order(body.order_id)
            if order.status in {"paid", "preparing", "shipped", "delivered"}:
                return result
            if order.status != "pending":
                raise ApiError(409, "Checkout has closed", "invalid_payment")
        if self._inventory:
            await self._inventory.check_order(order.lines)
        if order.discount_krw:
            await self._validate_coupon(order)
        try:
            status = await self._approver.approve(body.payment_key, order.id, order.amount_krw)
        except ApiError as exc:
            if order.discount_krw and exc.code == "payment_declined":
                order.status = "canceled"
                await self._orders.commit()
            raise
        if order.discount_krw and status != "DONE":
            raise ApiError(409, "Payment confirmation is pending", "payment_pending")
        await self._record_paid(order, body.payment_key)
        return result

    async def _validate_coupon(self, order):
        coupon = (
            await self._rewards.repo.coupon(order.user_id, order.reward_coupon_id)
            if order.reward_coupon_id
            else None
        )
        if coupon is None or coupon.expires_at <= datetime.now(UTC):
            raise ApiError(409, "Coupon is no longer valid", "coupon_unavailable")


def get_payment_service(session: AsyncSession = Depends(get_session)) -> PaymentService:
    settings = get_settings()
    return PaymentService(
        OrderRepository(session),
        CatalogRepository(session),
        TossPaymentsClient(settings.toss_secret_key),
        settings,
        InventoryService(InventoryRepository(session)) if settings.admin_enabled else None,
        RewardService(RewardRepository(session)),
    )
