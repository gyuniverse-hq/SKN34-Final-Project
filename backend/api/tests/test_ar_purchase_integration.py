"""AR purchase attribution and experiment totals with the existing PostgreSQL schema."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from app.main import create_app
from app.models.catalog import ProductRow, ShadeRow
from app.models.member import MemberRow
from app.models.raw_oliveyoung import RawOyProductRow, RawOyReviewSummaryRow
from app.models.recommendation_feedback import UserBehaviorEventRow
from app.repositories.ar_palette_repository import ArPaletteDatasetRepository
from app.services.ar_palette_service import experiment_arm
from app.services.ar_palette_training_service import summarize_experiment
from app.services.member_service import TERMS_VERSION


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("AR_PURCHASE_TEST_URL"), reason="needs migrated PostgreSQL")
@pytest.mark.parametrize("ml_baseline", [False, True], ids=["rule-baseline", "ml-baseline"])
def test_purchase_experiment_links_only_verified_order_lines_and_keeps_cart_label(
    monkeypatch, tmp_path, ml_baseline
):
    experiment = "ar-purchase-qa"
    identities = [f"ar-pay-{uuid4().hex}" for _ in range(40)]
    a_paid, a_idle = [u for u in identities if experiment_arm(experiment, u) == "A"][:2]
    b_paid, b_pending = [u for u in identities if experiment_arm(experiment, u) == "B"][:2]
    members = {a_paid, a_idle, b_paid, b_pending}
    actor = a_paid
    control_dir = Path("control") if ml_baseline else None
    candidate_dir = Path("candidate")
    settings = get_settings()
    for key, value in {
        "ar_palette_mode": "experiment",
        "ar_palette_experiment": experiment,
        "ar_palette_baseline_model_dir": control_dir,
        "ar_palette_model_dir": candidate_dir,
        "ar_palette_data_dir": tmp_path,
        "toss_client_key": "test-client",
        "payment_web_base_url": "http://test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    model_paths = []

    def score(config, rows, model_dir):
        bundle = model_dir or config.ar_palette_model_dir
        model_paths.append(bundle)
        return [row[2] for row in rows], f"m-{bundle.name}"

    monkeypatch.setattr("app.services.ar_palette_service.model_scores", score)
    approval = AsyncMock()
    monkeypatch.setattr("app.services.payment_service.TossPaymentsClient.approve", approval)
    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(id=actor, email=None)

    async def replay(conn):
        nonlocal actor

        async def sessions():
            async with AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                yield db

        app.dependency_overrides[get_session] = sessions
        now = datetime.now(UTC)
        goods = "arfixture-" + uuid4().hex
        product_id = "oy-" + goods
        async with AsyncSession(conn, join_transaction_mode="create_savepoint") as db:
            db.add_all(
                MemberRow(
                    id=u,
                    terms_version=TERMS_VERSION,
                    terms_agreed_at=now,
                    skin_subscription_until=now + timedelta(days=30),
                )
                for u in members
            )
            db.add(
                ProductRow(
                    id=product_id,
                    position=1,
                    brand="Fixture",
                    name="Lip",
                    name_ko="립",
                    category="lip",
                    makeup_zone="lip",
                    texture="matte",
                    price_krw=1000,
                    volume="3 g",
                    description="",
                    key_ingredients=[],
                    tags=[],
                    image_url="",
                    search_keyword="",
                    search_text="fixture",
                    shades=[
                        ShadeRow(
                            id="s",
                            position=0,
                            name="Pink",
                            hex="#C26471",
                            measure_method="estimated",
                        ),
                        ShadeRow(
                            id="other",
                            position=1,
                            name="Rose",
                            hex="#8B3B51",
                            measure_method="estimated",
                        ),
                    ],
                )
            )
            db.add(RawOyProductRow(goods_no=goods))
            await db.flush()
            db.add(
                RawOyReviewSummaryRow(
                    goods_no=goods,
                    review_count=100,
                    rating_avg=4.5,
                    is_latest=True,
                    collected_at=(now - timedelta(days=1)).replace(tzinfo=None),
                )
            )
            await db.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def post(path, body):
                response = await client.post(path, json=body)
                assert response.status_code == 200, response.text
                return response.json()

            async def rank(owner, *, add):
                nonlocal actor
                actor = owner
                sid, request, impression, cart = (str(uuid4()) for _ in range(4))
                decision = await post(
                    "/api/me/ar-history/rank",
                    {
                        "requestId": request,
                        "sessionId": sid,
                        "makeupZone": "lip",
                        "shades": [{"productId": product_id, "shadeId": "s"}],
                    },
                )
                if add:
                    await post(
                        "/api/me/ar-history/impressions",
                        {
                            "impressionId": impression,
                            "candidateId": decision["candidates"][0]["candidateId"],
                            "viewInstanceId": str(uuid4()),
                            "displayedPosition": 1,
                            "occurredAt": datetime.now(UTC).isoformat(),
                            "visibilityPolicyVersion": "direct-interaction-v1",
                        },
                    )
                    await post(
                        "/api/me/ar-history/events",
                        {
                            "eventId": cart,
                            "sessionId": sid,
                            "impressionId": impression,
                            "makeupZone": "lip",
                            "productId": product_id,
                            "shadeId": "s",
                            "eventType": "cart_add",
                            "occurredAt": datetime.now(UTC).isoformat(),
                        },
                    )
                return cart, impression

            async def create_order(owner, cart, *, shade="s"):
                nonlocal actor
                actor = owner
                order = await post(
                    "/api/payments/orders",
                    {
                        "lines": [
                            {
                                "productId": product_id,
                                "shadeId": shade,
                                "quantity": 1,
                                "arCartEventIds": [cart],
                            }
                        ]
                    },
                )
                token = parse_qs(urlparse(order["checkoutUrl"]).query)["token"][0]
                return {
                    "orderId": order["orderId"],
                    "paymentKey": uuid4().hex,
                    "amount": order["amount"],
                    "checkoutToken": token,
                }

            cart_a, impression_a = await rank(a_paid, add=True)
            await rank(a_idle, add=False)
            cart_b, impression_b = await rank(b_paid, add=True)
            cart_pending, _ = await rank(b_pending, add=True)
            wrong_owner = await create_order(a_idle, cart_b)
            wrong_shade = await create_order(a_paid, cart_a, shade="other")
            paid_a = await create_order(a_paid, cart_a)
            paid_b = await create_order(b_paid, cart_b)
            await create_order(b_pending, cart_pending)
            for order in (wrong_owner, wrong_shade, paid_a, paid_b, paid_a):
                assert (await post("/api/payments/confirm", order))["status"] == "paid"
            reused = await create_order(a_paid, cart_a)
            assert (await post("/api/payments/confirm", reused))["status"] == "paid"
            assert approval.await_count == 5

        baseline_paths = [control_dir, control_dir] if ml_baseline else []
        assert model_paths == [*baseline_paths, candidate_dir, candidate_dir]
        async with AsyncSession(conn, join_transaction_mode="create_savepoint") as db:
            events = (
                await db.scalars(
                    select(UserBehaviorEventRow).where(
                        UserBehaviorEventRow.member_id.in_(members),
                    )
                )
            ).all()
            purchases = [event for event in events if event.event_type == "purchase_confirmed"]
            assert len(purchases) == 2
            assert {event.context_snapshot["ar_impression_id"] for event in purchases} == {
                impression_a,
                impression_b,
            }
            assert all(event.order_line_id and event.impression_id is None for event in purchases)
            assert sum(event.event_type == "cart_add" for event in events) == 3
            repo = ArPaletteDatasetRepository(db)
            options = dict(
                experiment=experiment,
                start=now - timedelta(hours=1),
                end=now + timedelta(hours=1),
                window=timedelta(days=1),
                grace=timedelta(days=1),
                terms=TERMS_VERSION,
            )
            early = await repo.experiment_sessions(
                **options, as_of=now + timedelta(days=3), purchase_window=timedelta(days=7)
            )
            assert len(early) == 4 and not any(row["mature"] for row in early)
            rows = await repo.experiment_sessions(
                **options, as_of=now + timedelta(days=8), purchase_window=timedelta(days=7)
            )
            assert all(row["mature"] for row in rows)
            results = summarize_experiment(
                rows, min_sessions=2, min_lift=0, finished=True, measure_purchase=True
            )
            a, b = (results["arms"][arm] for arm in ("A", "B"))
            assert a["model_versions"] == (["m-control"] if ml_baseline else [])
            assert a["rule_sessions"] == (0 if ml_baseline else 2)
            assert b["model_versions"] == ["m-candidate"] and b["rule_sessions"] == 0
            assert (a["cart_to_purchase_rate"], b["cart_to_purchase_rate"]) == (1, 0.5)
            assert a["session_to_purchase_rate"] == b["session_to_purchase_rate"] == 0.5
            assert results["decision_metric"] == "session_to_purchase_rate"
            assert results["lift"] == 0.5
            assert results["result"] == "retain_baseline"
            labeled = [
                row
                async for row in repo.exposures(
                    as_of=now + timedelta(days=8),
                    window=timedelta(days=1),
                    grace=timedelta(days=1),
                    terms=TERMS_VERSION,
                )
            ]
            labeled = [row for row in labeled if row["member_id"] in members]
            assert len(labeled) == 3 and all(row["added_to_cart"] for row in labeled)

    async def verify():
        engine = create_async_engine(os.environ["AR_PURCHASE_TEST_URL"])
        try:
            async with engine.connect() as conn, conn.begin() as tx:
                await replay(conn)
                await tx.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
