import base64
from typing import Protocol

import httpx

from app.core.errors import ApiError


class PaymentApprover(Protocol):
    async def approve(self, payment_key: str, order_id: str, amount: int) -> None: ...


class TossPaymentsClient:
    def __init__(self, secret_key: str | None) -> None:
        self._secret_key = secret_key

    async def approve(self, payment_key: str, order_id: str, amount: int) -> None:
        if not self._secret_key:
            raise ApiError(503, "Payments are not configured", "payment_unavailable")
        basic = base64.b64encode(f"{self._secret_key}:".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.tosspayments.com/v1/payments/confirm",
                    headers={"Authorization": f"Basic {basic}"},
                    json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                )
        except httpx.HTTPError as exc:
            raise ApiError(502, "Payment provider is unavailable", "payment_upstream") from exc
        if response.status_code >= 400:
            raise ApiError(400, "Payment approval failed", "payment_failed")
