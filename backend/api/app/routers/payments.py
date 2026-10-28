# ruff: noqa: E501
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.core.auth import AuthUser, require_user
from app.schemas.payment import (
    ConfirmPaymentRequest,
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentResult,
)
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


@api.post("/confirm", response_model=PaymentResult)
async def confirm(
    body: ConfirmPaymentRequest, service: PaymentService = Depends(get_payment_service)
) -> PaymentResult:
    return await service.confirm(body)


@router.get("/pay/success", response_class=HTMLResponse)
async def success() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><p>결제를 확인하고 있어요…</p><script>(async()=>{const q=new URLSearchParams(location.search);const r=await fetch('/api/payments/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({orderId:q.get('orderId'),paymentKey:q.get('paymentKey'),amount:Number(q.get('amount')),checkoutToken:q.get('token')})});const d=await r.json();location.href=r.ok?d.returnUrl+'?orderId='+encodeURIComponent(d.orderId):'kbeautyar://payment-result?status=failed'})()</script>"""
    )


@router.get("/pay/fail", response_class=HTMLResponse)
async def fail() -> HTMLResponse:
    return HTMLResponse('<script>location.href="kbeautyar://payment-result?status=failed"</script>')


# Declared after /pay/success and /pay/fail so those fixed paths are not captured as an order id.
@router.get("/pay/{order_id}", response_class=HTMLResponse)
async def checkout(
    order_id: str,
    token: str = Query(min_length=32, max_length=128),
    service: PaymentService = Depends(get_payment_service),
) -> HTMLResponse:
    order = await service.checkout(order_id, token)
    settings = service._settings
    data = json.dumps({"clientKey": settings.toss_client_key, **order.model_dump()})
    return HTMLResponse(
        f"""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><div id="payment-method"></div><div id="agreement"></div><button id="pay">결제하기</button><script src="https://js.tosspayments.com/v2/standard"></script><script>const d={data};(async()=>{{const t=TossPayments(d.clientKey);const w=t.widgets({{customerKey:'ANONYMOUS'}});await w.setAmount({{currency:'KRW',value:d.amount}});await Promise.all([w.renderPaymentMethods({{selector:'#payment-method',variantKey:'DEFAULT'}}),w.renderAgreement({{selector:'#agreement',variantKey:'AGREEMENT'}})]);document.querySelector('#pay').onclick=()=>w.requestPayment({{orderId:d.order_id,orderName:d.order_name,successUrl:location.origin+'/pay/success?token='+encodeURIComponent(d.checkout_token),failUrl:location.origin+'/pay/fail'}})}})();</script>"""
    )
