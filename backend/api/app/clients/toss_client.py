import base64
import hashlib
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import ApiError


class PaymentApprover(Protocol):
    async def approve(self, payment_key: str, order_id: str, amount: int) -> None: ...


class TossPaymentsClient:
    def __init__(self, secret_key: str | None) -> None:
        self._secret_key = secret_key

    async def cancel(self, payment_key: str, reason: str) -> None:
        if not self._secret_key:
            raise ApiError(502, "Payment cancellation is unavailable", "payment_cancel_failed")
        basic = base64.b64encode(f"{self._secret_key}:".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.tosspayments.com/v1/payments/"
                    f"{quote(payment_key, safe='')}/cancel",
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Idempotency-Key": "admin-cancel-"
                        + hashlib.sha256(payment_key.encode()).hexdigest(),
                    },
                    json={"cancelReason": reason},
                )
        except httpx.HTTPError as exc:
            raise ApiError(502, "Payment cancellation failed", "payment_cancel_failed") from exc
        if response.status_code >= 400:
            raise ApiError(502, "Payment cancellation failed", "payment_cancel_failed")

    async def approve(self, payment_key: str, order_id: str, amount: int) -> None:
        if not self._secret_key:
            raise ApiError(503, "Payments are not configured", "payment_unavailable")
        basic = base64.b64encode(f"{self._secret_key}:".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.tosspayments.com/v1/payments/confirm",
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Idempotency-Key": "approve-"
                        + hashlib.sha256(payment_key.encode()).hexdigest(),
                    },
                    json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                )
        except httpx.HTTPError as exc:
            raise ApiError(502, "Payment provider is unavailable", "payment_upstream") from exc
        if response.status_code >= 400:
            raise ApiError(400, "Payment approval failed", "payment_failed")
