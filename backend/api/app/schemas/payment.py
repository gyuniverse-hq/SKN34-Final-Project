from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrderLineRequest(BaseModel):
    product_id: str = Field(alias="productId", min_length=1, max_length=64)
    shade_id: str | None = Field(default=None, alias="shadeId", max_length=64)
    quantity: int = Field(ge=1, le=20)
    ar_cart_event_ids: list[UUID] = Field(
        default_factory=list, alias="arCartEventIds", max_length=20
    )
    skincare_cart_event_ids: list[UUID] = Field(
        default_factory=list, alias="skincareCartEventIds", max_length=20
    )
    cart_recommendation_event_ids: list[UUID] = Field(
        default_factory=list, alias="cartRecommendationEventIds", max_length=20
    )


class CreateOrderRequest(BaseModel):
    coupon_id: UUID | None = Field(None, alias="couponId")
    lines: list[OrderLineRequest] = Field(min_length=1, max_length=30)
    cart_visit_id: UUID | None = Field(default=None, alias="cartVisitId")


class CreateOrderResponse(BaseModel):
    order_id: str = Field(alias="orderId")
    amount: int
    checkout_url: str = Field(alias="checkoutUrl")
    local_checkout_path: str | None = Field(None, alias="localCheckoutPath")


class ConfirmPaymentRequest(BaseModel):
    order_id: str = Field(alias="orderId", min_length=6, max_length=64)
    payment_key: str = Field(alias="paymentKey", min_length=1, max_length=200)
    amount: int = Field(gt=0)
    checkout_token: str = Field(alias="checkoutToken", min_length=32, max_length=128)


class PaymentResult(BaseModel):
    order_id: str = Field(alias="orderId")
    status: Literal["paid"]
    return_url: str = Field(alias="returnUrl")


class OrderStatus(BaseModel):
    order_id: str = Field(alias="orderId")
    status: Literal["pending", "paid", "preparing", "shipped", "delivered", "canceled"]


class PublicCheckout(BaseModel):
    order_id: str
    order_name: str
    amount: int
    checkout_token: str
