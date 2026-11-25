"""Cart recommendation continuation, attribution, and A/B reporting against PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.main import create_app
from app.models.admin import ProductAdminStateRow
from app.models.ar_personalization import ArRecommendationImpressionRow, ArRecommendationRequestRow
from app.models.catalog import ProductRow, ShadeRow
from app.models.member import MemberRow
from app.models.order import OrderLineRow, OrderRow
from app.models.raw_oliveyoung import RawOyProductRow, RawOyReviewSummaryRow
from app.models.recommendation_feedback import UserBehaviorEventRow
from app.services.ar_palette_service import experiment_arm
from app.services.cart_recommendation_service import experiment_report
from app.services.member_service import TERMS_VERSION

PATH = "/api/me/cart-recommendations"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("CART_RECOMMENDATION_TEST_URL"), reason="needs migrated PostgreSQL"
)
@pytest.mark.parametrize("admin_enabled", [False, True], ids=["payments", "admin-inventory"])
def test_cart_recommendation_attribution_and_ab_report(monkeypatch, tmp_path, admin_enabled):
    experiment = "cart-recs-qa"
    members = {}
    while len(members) < 2:
        owner = str(uuid4())
        members[experiment_arm(f"cart:{experiment}", owner)] = owner
    owner_a, owner_b = (members[arm] for arm in ("A", "B"))
    actor = owner_b
    settings = get_settings()
    for key, value in {
        "admin_enabled": admin_enabled,
        "ar_palette_mode": "collect",
        "ar_palette_data_dir": tmp_path,
        "cart_recommendation_experiment": experiment,
        "toss_client_key": "cart-test-client",
        "payment_web_base_url": "http://test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    approval = AsyncMock()
    monkeypatch.setattr("app.services.payment_service.TossPaymentsClient.approve", approval)
    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(id=actor, email=None)

    async def replay(conn):
        nonlocal actor

        def session():
            return AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        async def sessions():
            async with session() as db:
                yield db

        app.dependency_overrides[get_session] = sessions
        monkeypatch.setattr("app.services.cart_recommendation_service.session_scope", session)
        now = datetime.now(UTC)
        stem = "oy-cartqa-" + uuid4().hex[:10]
        lip = [f"{stem}-lip-{i}" for i in range(6)]
        blush = [f"{stem}-blush-{i}" for i in range(5)]
        unavailable_blush = [f"{stem}-hidden", f"{stem}-sold-out"] if admin_enabled else []
        products = [*lip, *blush, *unavailable_blush]
        async with session() as db:
            db.add_all(
                MemberRow(
                    id=owner,
                    terms_version=TERMS_VERSION,
                    terms_agreed_at=now,
                    ar_activity_consented_at=now,
                    skin_subscription_until=now + timedelta(days=30),
                )
                for owner in members.values()
            )
            for product in products:
                zone = "lip" if product in lip else "blush"
                db.add(
                    ProductRow(
                        id=product,
                        position=1,
                        brand="Fixture",
                        name="Makeup",
                        name_ko="화장품",
                        category="lip" if zone == "lip" else "cheek",
                        makeup_zone=zone,
                        texture="matte",
                        price_krw=0 if product == blush[4] else 1000,
                        volume="3 g",
                        description="",
                        key_ingredients=[],
                        tags=[],
                        image_url="",
                        search_keyword="",
                        search_text="",
                        shades=[
                            ShadeRow(
                                id="s",
                                name="Shade",
                                hex="#F2945B" if product == blush[3] else "#C26471",
                                measure_method="estimated",
                            )
                        ],
                    )
                )
                db.add(RawOyProductRow(goods_no=product[3:]))
            await db.flush()
            if admin_enabled:
                hidden, sold_out = unavailable_blush
                db.add_all(
                    [
                        ProductAdminStateRow(product_id=hidden, is_visible=False),
                        ProductAdminStateRow(product_id=sold_out, stock=0),
                        ProductAdminStateRow(product_id=lip[3], stock=4),
                    ]
                )
            db.add_all(
                RawOyReviewSummaryRow(
                    goods_no=product[3:],
                    review_count=100,
                    rating_avg=5.0 if product in unavailable_blush else 4.5,
                    is_latest=True,
                    collected_at=(now - timedelta(days=1)).replace(tzinfo=None),
                )
                for product in products
            )
            await db.commit()

        def item(product):
            return {"productId": product, "shadeId": "s"}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def post(path, body, code=200):
                response = await client.post(path, json=body)
                assert response.status_code == code, response.text
                return response.json()

            async def order(visit_id, lines, *, paid=True):
                result = await post(
                    "/api/payments/orders", {"cartVisitId": visit_id, "lines": lines}
                )
                if paid:
                    token = parse_qs(urlparse(result["checkoutUrl"]).query)["token"][0]
                    confirmation = {
                        "orderId": result["orderId"],
                        "amount": result["amount"],
                        "paymentKey": uuid4().hex,
                        "checkoutToken": token,
                    }
                    assert (await post("/api/payments/confirm", confirmation))["status"] == "paid"
                return result["orderId"]

            request_id = str(uuid4())
            rank = await post(
                "/api/me/ar-history/rank",
                {
                    "requestId": request_id,
                    "sessionId": str(uuid4()),
                    "makeupZone": "lip",
                    "shades": [item(product) for product in lip],
                },
            )
            assert [card["productId"] for card in rank["candidates"]] == lip[:3]
            body = {
                "cartVisitId": str(uuid4()),
                "items": [item(lip[0])],
                "arRequestIds": {"lip": request_id, "blush": request_id},
            }
            shown = await post(PATH, body)
            assert await post(PATH, {**body, "items": [item(lip[5])]}) == shown
            cards = shown["candidates"]
            assert [card["productId"] for card in cards] == blush[:3] + lip[3:5]
            assert [card["arRequestId"] for card in cards] == [None] * 3 + [request_id] * 2
            assert [card["originalRank"] for card in cards[3:]] == [4, 5]
            assert [card["position"] for card in cards] == [1, 2, 3, 4, 5]

            visibility = {
                "cartVisitId": shown["cartVisitId"],
                "candidateId": cards[3]["candidateId"],
                "impressionId": str(uuid4()),
                "visibilityPolicyVersion": "direct-interaction-v1",
            }
            first = await post(PATH + "/impressions", visibility)
            assert (
                await post(PATH + "/impressions", {**visibility, "impressionId": str(uuid4())})
                == first
            )
            addition = {"eventId": str(uuid4()), "impressionId": first["impressionId"]}
            await post(PATH + "/cart-adds", addition)
            await post(PATH + "/cart-adds", addition)
            bought_line = {
                **item(lip[3]),
                "quantity": 1,
                "cartRecommendationEventIds": [addition["eventId"]],
            }
            paid_b = await order(shown["cartVisitId"], [bought_line])

            actor = owner_a
            await post(PATH, body, 409)
            await post(PATH + "/impressions", visibility, 409)
            await post(PATH + "/cart-adds", addition, 409)
            forged = await order(shown["cartVisitId"], [bought_line], paid=False)
            control = await post(PATH, {"cartVisitId": str(uuid4()), "items": [item(lip[0])]})
            assert control["candidates"] == []
            existing_line = {**item(lip[0]), "quantity": 1}
            await order(control["cartVisitId"], [existing_line])
            organic = await post(PATH, {"cartVisitId": str(uuid4()), "items": [item(lip[0])]})
            await order(organic["cartVisitId"], [existing_line, bought_line])

            actor = owner_b
            async with session() as db:
                ar_request = await db.get(ArRecommendationRequestRow, UUID(request_id))
                assert ar_request.cart_candidates == [[product, "s"] for product in lip[3:]]
                ar_request.cart_candidates = None
                await db.commit()
            fallback = await post(PATH, {**body, "cartVisitId": str(uuid4())})
            assert len(fallback["candidates"]) == 5
            assert {card["productId"] for card in fallback["candidates"]}.isdisjoint(lip[:3])
            assert all(card["arRequestId"] is None for card in fallback["candidates"])
            await order(fallback["cartVisitId"], [bought_line], paid=False)
            monkeypatch.setattr(settings, "ar_palette_mode", "experiment")
            monkeypatch.setattr(settings, "ar_palette_experiment", "")
            empty = await post(PATH, {"cartVisitId": str(uuid4()), "items": [item(lip[0])]})
            assert empty["candidates"] == []
            monkeypatch.setattr(settings, "cart_recommendation_experiment", "")
            assert await post(PATH, {"cartVisitId": str(uuid4()), "items": [item(lip[0])]}) is None

        assert approval.await_count == 3
        async with session() as db:
            assert (await db.get(OrderRow, forged)).cart_visit_id is None
            paid_order = await db.get(OrderRow, paid_b)
            assert paid_order.paid_at is not None
            bought = await db.scalar(select(OrderLineRow).where(OrderLineRow.order_id == paid_b))
            assert str(bought.cart_recommendation_event_id) == addition["eventId"]
            if admin_enabled:
                assert bought.stock_debited == 1
                assert (await db.get(ProductAdminStateRow, lip[3])).stock == 2
                paid_order.status = "shipped"
                await db.commit()
            event = await db.get(UserBehaviorEventRow, UUID(addition["eventId"]))
            assert event.surface == "cart_recommendations"
            assert event.context_snapshot["impression_id"] == first["impressionId"]
            assert await db.scalar(select(ArRecommendationImpressionRow)) is None

        timing = dict(
            experiment=experiment,
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
            window_hours=24,
        )
        early = await experiment_report(**timing, as_of=now + timedelta(minutes=1))
        assert early["arms"]["A"]["pending_visits"] == 2
        assert early["arms"]["B"]["new_product_paid_rate"] is None
        report = await experiment_report(**timing, as_of=now + timedelta(days=2))
        a, b = (report["arms"][arm] for arm in ("A", "B"))
        assert (a["paid_rate"], a["new_product_paid_rate"]) == (1.0, 0.5)
        assert (b["paid_rate"], b["new_product_paid_rate"]) == (1 / 3, 1 / 3)
        assert (
            b["exposed_visits"],
            b["recommendation_add_visits"],
            b["recommendation_paid_visits"],
        ) == (1, 1, 1)
        assert (a["served_visits"], b["served_visits"]) == (0, 2)

    async def verify():
        engine = create_async_engine(os.environ["CART_RECOMMENDATION_TEST_URL"])
        try:
            async with engine.connect() as conn, conn.begin() as transaction:
                await replay(conn)
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
