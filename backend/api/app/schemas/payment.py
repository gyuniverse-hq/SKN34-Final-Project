from typing import Literal

from pydantic import BaseModel, Field


class OrderLineRequest(BaseModel):
    product_id: str = Field(alias="productId", min_length=1, max_length=64)
    shade_id: str | None = Field(default=None, alias="shadeId", max_length=64)
    quantity: int = Field(ge=1, le=20)


class CreateOrderRequest(BaseModel):
    lines: list[OrderLineRequest] = Field(min_length=1, max_length=30)


class CreateOrderResponse(BaseModel):
    order_id: str = Field(alias="orderId")
    amount: int
    checkout_url: str = Field(alias="checkoutUrl")


class ConfirmPaymentRequest(BaseModel):
    order_id: str = Field(alias="orderId", min_length=6, max_length=64)
    payment_key: str = Field(alias="paymentKey", min_length=1, max_length=200)
    amount: int = Field(gt=0)
    checkout_token: str = Field(alias="checkoutToken", min_length=32, max_length=128)


class PaymentResult(BaseModel):
    order_id: str = Field(alias="orderId")
    status: Literal["paid"]
    return_url: str = Field(alias="returnUrl")


class PublicCheckout(BaseModel):
    order_id: str
    order_name: str
    amount: int
    checkout_token: str
