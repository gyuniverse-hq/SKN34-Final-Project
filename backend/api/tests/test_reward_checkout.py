"""Exercise authenticated coupon checkout in a rolled-back PostgreSQL transaction."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.clients.toss_client import TossPaymentsClient
from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.main import create_app
from app.models.member import MemberRow
from app.models.reward import RewardAttendanceRow, RewardCouponRow
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import StatusChange
from app.services.admin_service import AdminService
from app.services.reward_service import KST


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("ATTENDANCE_MIGRATION_TEST_URL"), reason="needs migrated PostgreSQL"
)
def test_attendance_coupon_checkout_and_recovery(monkeypatch):
    owner, outsider = (uuid4().hex for _ in range(2))
    now = datetime.now(UTC)
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_enabled", False)
    monkeypatch.setattr(settings, "toss_client_key", "test")
    monkeypatch.setattr(settings, "toss_secret_key", "test_example")
    monkeypatch.setattr(settings, "payment_web_base_url", "http://test")
    product = SimpleNamespace(id="test-shade", price_krw=25000, shades=[])
    monkeypatch.setattr(
        "app.repositories.catalog_repository.CatalogRepository.get_product",
        AsyncMock(return_value=product),
    )
    provider = AsyncMock()
    lookup = AsyncMock()
    monkeypatch.setattr(TossPaymentsClient, "approve", provider)
    monkeypatch.setattr(TossPaymentsClient, "lookup", lookup)
    app = create_app()
    actor = owner
    app.dependency_overrides[require_user] = lambda: AuthUser(id=actor, email=None)

    async def exercise(conn):
        nonlocal actor

        def session():
            return AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        async def sessions():
            async with session() as db:
                yield db

        app.dependency_overrides[get_session] = sessions
        async with session() as db:
            db.add(
                MemberRow(
                    id=owner,
                    terms_version="test",
                    terms_agreed_at=now,
                    skin_subscription_until=now + timedelta(days=30),
                )
            )
            await db.flush()
            for i in range(1, 6):
                db.add(
                    RewardAttendanceRow(
                        member_id=owner,
                        stamp_goal=7,
                        attendance_date=now.astimezone(KST).date() - timedelta(days=i),
                    )
                )
            await db.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def post(path, body=None, status=200):
                response = await client.post(path, json=body or {})
                assert response.status_code == status, response.text
                return response.json()

            async def wallet():
                return (await client.get("/api/me/rewards")).json()

            async def create(status=200):
                return await post(
                    "/api/payments/orders",
                    {"lines": [{"productId": product.id, "quantity": 1}], "couponId": coupon},
                    status,
                )

            async def close(order):
                return (await post("/api/payments/orders/" + order["orderId"] + "/close"))["status"]

            async def confirm(order, status=200):
                token = parse_qs(urlsplit(order["checkoutUrl"]).query)["token"][0]
                return await post(
                    "/api/payments/confirm",
                    {
                        "orderId": order["orderId"],
                        "paymentKey": "key-" + order["orderId"],
                        "amount": order["amount"],
                        "checkoutToken": token,
                    },
                    status,
                )

            stamp = await post("/api/me/rewards/attendance")
            assert (stamp["checkedToday"], stamp["goal"], stamp["stamps"]) == (True, 4, 2)
            coupon = stamp["coupons"][0]["id"]
            assert stamp == await post("/api/me/rewards/attendance")
            actor = outsider
            await create(409)
            actor = owner
            product.price_krw = 9999
            await create(409)
            product.price_krw = 10000
            first = await create()
            assert first["amount"] == 9000
            assert first["localCheckoutPath"].startswith("/pay/" + first["orderId"] + "?token=")
            await create(409)
            assert (await wallet())["coupons"][0]["reservedOrderId"] == first["orderId"]
            assert await close(first) == "canceled"
            await confirm(first, 409)
            assert (await wallet())["coupons"][0]["status"] == "available"
            product.price_krw = 25000
            second = await create()
            assert second["amount"] == 23000
            provider.side_effect = ApiError(502, "timeout", "payment_upstream")
            await confirm(second, 502)
            lookup.return_value = "IN_PROGRESS"
            assert await close(second) == "pending"
            lookup.return_value = "EXPIRED"
            assert await close(second) == "canceled"
            third = await create()
            await confirm(third, 502)
            lookup.return_value = "DONE"
            assert await close(third) == "paid"
            assert await close(third) == "paid"
            assert (await confirm(third))["status"] == "paid"
            assert (await wallet())["coupons"][0]["status"] == "used"
            assert provider.await_count == 2
            refund = AsyncMock()

            async def cancel_paid(order):
                async with session() as db:
                    admin = AdminService(AdminRepository(db), refund, None)
                    await admin.change_status(
                        order["orderId"], StatusChange(status="canceled", reason="test"), owner
                    )

            await cancel_paid(third)
            assert (await wallet())["coupons"][0]["status"] == "available"
            fourth = await create()
            provider.side_effect = None
            provider.return_value = "DONE"
            await confirm(fourth)
            await confirm(fourth)
            assert provider.await_count == 3

            async with session() as db:
                issued = await db.get(RewardCouponRow, UUID(coupon))
                issued.issued_at = now - timedelta(days=8)
                issued.expires_at = now - timedelta(days=1)
                await db.commit()
            await cancel_paid(fourth)
            assert refund.cancel.await_count == 2
            assert (await wallet())["coupons"][0]["status"] == "expired"
            await create(409)

    async def run():
        engine = create_async_engine(os.environ["ATTENDANCE_MIGRATION_TEST_URL"])
        try:
            async with engine.connect() as conn, conn.begin() as transaction:
                await exercise(conn)
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
