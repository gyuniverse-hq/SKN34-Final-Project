import base64
import hashlib
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import ApiError


class PaymentApprover(Protocol):
    async def lookup(self, payment_key: str, order_id: str, amount: int) -> str: ...
    async def approve(self, payment_key: str, order_id: str, amount: int) -> str: ...


class TossPaymentsClient:
    def __init__(self, secret_key: str | None) -> None:
        self._secret_key = secret_key

    async def lookup(self, payment_key: str, order_id: str, amount: int) -> str:
        if not self._secret_key:
            raise ApiError(503, "Payments are not configured", "payment_unavailable")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://api.tosspayments.com/v1/payments/" + quote(payment_key, safe=""),
                    auth=(self._secret_key, ""),
                )
            if response.status_code == 404 and response.json().get("code") == "NOT_FOUND_PAYMENT":
                return "NOT_FOUND"
            response.raise_for_status()
            data = response.json()
            if (
                data.get("orderId") == order_id
                and data.get("totalAmount") == amount
                and data.get("paymentKey") == payment_key
            ):
                return data["status"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ApiError(502, "Cannot verify payment status", "payment_upstream") from exc
        raise ApiError(409, "Payment does not match this order", "invalid_payment")

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

    async def approve(self, payment_key: str, order_id: str, amount: int) -> str:
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
            error = (
                response.json().get("code", "")
                if response.headers.get("content-type", "").startswith("application/json")
                else ""
            )
            if response.status_code < 500 and error in {
                "REJECT_ACCOUNT_PAYMENT",
                "REJECT_CARD_PAYMENT",
                "REJECT_CARD_COMPANY",
                "NOT_FOUND_PAYMENT_SESSION",
            }:
                raise ApiError(400, "Payment was declined", "payment_declined")
            raise ApiError(400, "Payment approval failed", "payment_failed")
        data = response.json()
        if (
            data.get("orderId") != order_id
            or data.get("paymentKey") != payment_key
            or data.get("totalAmount") != amount
            or not isinstance(data.get("status"), str)
        ):
            raise ApiError(502, "Unexpected payment response", "payment_upstream")
        return data["status"]
