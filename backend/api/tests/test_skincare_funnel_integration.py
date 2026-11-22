"""Exercise skincare routes and attribution in PostgreSQL with a stub payment provider."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.main import create_app
from app.models.member import MemberRow
from app.models.recommendation_feedback import (
    RecommendationRequestRow,
    SkincareRecommendationEventRow,
    UserBehaviorEventRow,
)
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.schemas.recommendation_feedback import SKINCARE_HISTORY_CONTRACT
from app.services.member_service import TERMS_VERSION
from app.services.recommendation_feedback_service import skincare_funnel_report
from app.services.skincare_service import SkincareService, get_skincare_service
from tests.test_skincare_profile_balance import catalog, request

PATH = "/api/recommendations/skincare/v4"


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("SKINCARE_FUNNEL_TEST_URL"), reason="needs migrated PostgreSQL")
def test_skincare_funnel_counts_exposure_cart_and_verified_purchases_in_its_own_table(monkeypatch):
    now = datetime.now(UTC)
    owner, other, non_consented = (f"skin-qa-{uuid4().hex}" for _ in range(3))
    settings = get_settings()
    monkeypatch.setattr(settings, "skin_recommendation_feedback_consented_members", {owner, other})
    monkeypatch.setattr(settings, "toss_client_key", "test")
    monkeypatch.setattr(settings, "payment_web_base_url", "http://test")
    approval = AsyncMock()
    monkeypatch.setattr("app.services.payment_service.TossPaymentsClient.approve", approval)
    snapshot = catalog()
    products = {option.product.id: option.product for option in snapshot.options}

    async def get_product(_self, product_id):
        return products.get(product_id)

    monkeypatch.setattr(
        "app.repositories.catalog_repository.CatalogRepository.get_product", get_product
    )
    app = create_app()
    actor = owner
    app.dependency_overrides[require_user] = lambda: AuthUser(id=actor, email=None)
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(
        SimpleNamespace(read=AsyncMock(return_value=snapshot))
    )

    async def verify(conn):
        nonlocal actor

        def sessions():
            return AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        async def dependency():
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_session] = dependency
        monkeypatch.setattr("app.services.recommendation_feedback_service.session_scope", sessions)
        async with sessions() as db:
            db.add_all(
                MemberRow(id=member, terms_version=TERMS_VERSION, terms_agreed_at=now)
                for member in (owner, other, non_consented)
            )
            await db.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def post(path, body, status=200):
                response = await client.post(path, json=body)
                assert response.status_code == status, response.text
                assert (
                    path.startswith("/api/payments/")
                    or status != 200
                    or (response.headers["cache-control"] == "no-store")
                )
                return response.json()

            async def recommend(member):
                nonlocal actor
                actor = member
                return await post(
                    f"{PATH}/recorded",
                    {
                        "sessionId": str(uuid4()),
                        "input": request().model_dump(mode="json"),
                    },
                )

            def exposure(match, rank):
                return {
                    "candidateId": match["candidateId"],
                    "impressionId": str(uuid4()),
                    "viewInstanceId": str(uuid4()),
                    "displayedPosition": rank,
                    "occurredAt": datetime.now(UTC).isoformat(),
                    "surface": "skin_recommendations",
                    "visibilityPolicyVersion": "direct-interaction-v1",
                }

            async def order(member, product, cart_id):
                nonlocal actor
                actor = member
                result = await post(
                    "/api/payments/orders",
                    {
                        "lines": [
                            {"productId": product, "quantity": 1, "skincareCartEventIds": [cart_id]}
                        ]
                    },
                )
                return {
                    "orderId": result["orderId"],
                    "paymentKey": uuid4().hex,
                    "amount": result["amount"],
                    "checkoutToken": parse_qs(urlparse(result["checkoutUrl"]).query)["token"][0],
                }

            guest = await post(PATH, request().model_dump(mode="json"))
            assert "history" not in guest
            unrecorded = await recommend(non_consented)
            assert unrecorded == guest
            first = await recommend(owner)
            assert len(first["overallTop10"]) == 10
            assert [item["product"] for item in first["overallTop10"]] == [
                item["product"] for item in guest["overallTop10"]
            ]
            assert first["overallTop5"] == first["overallTop10"][:5]
            await recommend(owner)  # Fetched but never exposed.
            viewed_only = await recommend(other)
            await post(f"{PATH}/impressions", exposure(viewed_only["overallTop10"][0], 1))
            match = first["overallTop10"][9]
            impression = exposure(match, 10)
            await post(f"{PATH}/impressions", impression, 404)  # Wrong member.
            actor = owner
            await post(f"{PATH}/impressions", impression | {"displayedPosition": 9}, 422)
            await post(f"{PATH}/impressions", impression)
            await post(f"{PATH}/impressions", impression)
            product = match["product"]["id"]
            cart = {
                "eventId": str(uuid4()),
                "impressionId": impression["impressionId"],
                "sessionId": first["history"]["sessionId"],
                "productId": product,
                "optionId": None,
                "eventType": "cart_add",
                "occurredAt": datetime.now(UTC).isoformat(),
            }
            await post("/api/recommendations/skin-v2/events", cart, 404)
            forged = await post(f"{PATH}/events", cart | {"eventType": "purchase_confirmed"}, 400)
            assert forged["code"] == "invalid_request"
            await post(f"{PATH}/events", cart | {"sessionId": str(uuid4())}, 422)
            await post(f"{PATH}/events", cart)
            await post(f"{PATH}/events", cart)
            await post(f"{PATH}/events", cart | {"eventId": str(uuid4())})  # Same product/session.

            cart_id = cart["eventId"]
            wrong_owner = await order(other, product, cart_id)
            wrong_product = await order(owner, first["overallTop10"][0]["product"]["id"], cart_id)
            pending = await order(owner, product, cart_id)
            paid = await order(owner, product, cart_id)
            duplicate = await order(owner, product, cart_id)
            approval.side_effect = ApiError(400, "Declined", "payment_failed")
            await post("/api/payments/confirm", pending, 400)
            approval.side_effect = None
            for payment in (wrong_owner, wrong_product, paid, paid, duplicate):
                assert (await post("/api/payments/confirm", payment))["status"] == "paid"
            assert approval.await_count == 5

        async with sessions() as db:
            request_rows = (await db.scalars(select(RecommendationRequestRow))).all()
            assert len(request_rows) == 3
            assert all(row.contract_version == SKINCARE_HISTORY_CONTRACT for row in request_rows)
            assert all(
                not row.input_snapshot and row.v2_model_version is None for row in request_rows
            )
            events = (await db.scalars(select(SkincareRecommendationEventRow))).all()
            purchases = [event for event in events if event.event_type == "purchase_confirmed"]
            assert len(purchases) == 1
            assert str(purchases[0].cart_event_id) == cart_id
            assert str(purchases[0].impression_id) == impression["impressionId"]
            assert not (await db.scalars(select(UserBehaviorEventRow))).all()

        start, as_of = now - timedelta(minutes=1), datetime.now(UTC) + timedelta(minutes=1)
        report = await skincare_funnel_report(start, as_of, as_of, settings)
        assert report == {
            "exposedSessions": 2,
            "cartSessions": 1,
            "purchaseSessions": 1,
            "cartedProducts": 1,
            "purchasedProducts": 1,
            "cartRate": 0.5,
            "cartedProductsPer100Sessions": 50.0,
            "cartToPurchaseRate": 1.0,
            "productCartToPurchaseRate": 1.0,
        }
        async with sessions() as db:
            repo = RecommendationFeedbackRepository(db)
            assert (await repo.skincare_funnel(start, as_of, as_of, settings.env, {other})) == {
                "exposedSessions": 1,
                "cartSessions": 0,
                "purchaseSessions": 0,
                "cartedProducts": 0,
                "purchasedProducts": 0,
            }

    async def run():
        engine = create_async_engine(os.environ["SKINCARE_FUNNEL_TEST_URL"])
        try:
            async with engine.connect() as connection, connection.begin() as transaction:
                await verify(connection)
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())
