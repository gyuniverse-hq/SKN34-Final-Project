from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.auth import AuthUser, require_user
from app.schemas.payment import (
    ConfirmPaymentRequest,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderStatus,
    PaymentResult,
)
from app.services.payment_pages import checkout_page, fail_page, success_page
from app.services.payment_service import PaymentService, get_payment_service

router = APIRouter(tags=["payments"])
api = APIRouter(prefix="/api/payments", tags=["payments"])


@api.post("/orders", response_model=CreateOrderResponse)
async def create_order(
    body: CreateOrderRequest,
    user: AuthUser = Depends(require_user),
    service: PaymentService = Depends(get_payment_service),
) -> CreateOrderResponse:
    return await service.create_order(user.id, body)


@api.get("/orders/{order_id}", response_model=OrderStatus)
async def order_status(
    order_id: str,
    user: AuthUser = Depends(require_user),
    service: PaymentService = Depends(get_payment_service),
) -> OrderStatus:
    return await service.order_status(user.id, order_id)


@api.post("/orders/{order_id}/close", response_model=OrderStatus)
async def close_checkout(
    order_id: str,
    user: AuthUser = Depends(require_user),
    service: PaymentService = Depends(get_payment_service),
) -> OrderStatus:
    return await service.close_checkout(user.id, order_id)


@api.post("/confirm", response_model=PaymentResult)
async def confirm(
    body: ConfirmPaymentRequest, service: PaymentService = Depends(get_payment_service)
) -> PaymentResult:
    return await service.confirm(body)


@router.get("/pay/success", response_class=HTMLResponse)
async def success() -> HTMLResponse:
    return HTMLResponse(success_page())


@router.get("/pay/fail", response_class=HTMLResponse)
async def fail() -> HTMLResponse:
    return HTMLResponse(fail_page())


# Declared after /pay/success and /pay/fail so those fixed paths are not captured as an order id.
@router.get("/pay/{order_id}", response_class=HTMLResponse)
async def checkout(
    order_id: str,
    token: str = Query(min_length=32, max_length=128),
    service: PaymentService = Depends(get_payment_service),
) -> HTMLResponse:
    order = await service.checkout(order_id, token)
    settings = service._settings
    return HTMLResponse(
        checkout_page(
            client_key=settings.toss_client_key or "",
            order_id=order.order_id,
            order_name=order.order_name,
            amount=order.amount,
            checkout_token=order.checkout_token,
        )
    )
