"""Exercise the HTTP contract against PostgreSQL without committing any test data."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.main import create_app
from app.services.member_service import TERMS_VERSION


def test_collection_requires_explicit_enrollment():
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    from app.services.ar_history_service import ArHistoryService, get_ar_history

    repo = AsyncMock()
    repo.access.return_value = (False, False)
    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(id="ordinary-member", email=None)

    app.dependency_overrides[get_ar_history] = lambda: ArHistoryService(repo)
    client = TestClient(app)
    assert client.post("/api/me/ar-history/palette", json={"makeupZone": "lip"}).status_code == 403
    assert client.post("/api/me/ar-history/status").json() == {
        "enabled": False,
        "recommendations": False,
    }
    res = client.post(
        "/api/me/ar-history/events",
        json={
            "eventId": str(uuid4()),
            "sessionId": str(uuid4()),
            "eventType": "try_on",
            "makeupZone": "lip",
            "productId": "p",
            "shadeId": "s",
            "occurredAt": datetime.now(UTC).isoformat(),
        },
    )
    assert res.status_code == 403


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("AR_HISTORY_TEST_URL"), reason="needs migrated PostgreSQL")
def test_http_to_db_with_replay_and_attribution():
    owner, other = ("ar-test-" + uuid4().hex for _ in range(2))
    app = create_app()
    actor = owner
    app.dependency_overrides[require_user] = lambda: AuthUser(id=actor, email=None)

    async def run(conn):
        nonlocal actor

        async def sessions():
            async with AsyncSession(
                conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            ) as db:
                yield db

        app.dependency_overrides[get_session] = sessions
        await conn.execute(
            text(
                "INSERT INTO members (id,terms_version,terms_agreed_at,"
                "skin_subscription_until) VALUES "
                "(:owner,:version,now()-interval '1 day',now()+interval '1 day'),"
                "(:other,'previous',now()-interval '1 day',now()-interval '1 day')"
            ),
            dict(owner=owner, other=other, version=TERMS_VERSION),
        )
        pid, sid = (
            await conn.execute(
                text(
                    "SELECT product_id, shades.id FROM shades "
                    "JOIN products ON products.id=product_id "
                    "WHERE makeup_zone='lip' LIMIT 1"
                )
            )
        ).one()
        req, session, candidate, imp, view, evt = (str(uuid4()) for _ in range(6))
        request = dict(
            requestId=req,
            sessionId=session,
            direction="similar",
            makeupZone="lip",
            candidates=[dict(productId=pid, shadeId=sid, candidateId=candidate)],
        )
        now = datetime.now(UTC).isoformat()
        exposure = dict(
            impressionId=imp,
            candidateId=candidate,
            viewInstanceId=view,
            displayedPosition=1,
            occurredAt=now,
            visibilityPolicyVersion="arc-inner-500ms-v1",
        )
        event = dict(
            eventId=evt,
            sessionId=session,
            impressionId=imp,
            occurredAt=now,
            productId=pid,
            shadeId=sid,
            makeupZone="lip",
            eventType="try_on",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/me/ar-history/"
        ) as client:

            async def post(path, body, status=200):
                res = await client.post(path, json=body)
                assert res.status_code == status, res.text
                return res.json()

            actor = other
            assert await post("status", {}) == {"enabled": False, "recommendations": False}
            await post("events", {**event, "eventId": str(uuid4()), "impressionId": None}, 403)
            accepted = await post("http://test/api/me/terms", {"version": TERMS_VERSION})
            assert await post("http://test/api/me/terms", {"version": TERMS_VERSION}) == accepted
            assert await post("status", {}) == {"enabled": True, "recommendations": False}
            await post("palette", {"makeupZone": "lip"}, 403)
            await post("requests", request, 403)
            await post(
                "events",
                {
                    **event,
                    "eventId": str(uuid4()),
                    "impressionId": None,
                    "occurredAt": datetime.now(UTC).isoformat(),
                },
            )
            assert (await client.post("http://test/api/me/skin-access/dev-subscription")).is_success
            assert await post("status", {}) == {"enabled": True, "recommendations": True}
            actor = owner

            cold = await post("palette", {"makeupZone": "lip"})
            assert cold["ratings"] and cold["preferences"] == []
            assert all(r["reviews"] > 0 and 1 <= r["rating"] <= 5 for r in cold["ratings"])

            for _ in range(2):
                await post("requests", request)
                await post("impressions", exposure)
                await post("events", event)
            await post("events", {**event, "eventType": "cart_add"}, 409)
            await post("requests", {**request, "candidates": []}, 409)
            await post("events", {**event, "eventId": str(uuid4()), "sessionId": str(uuid4())}, 404)
            await post(
                "events",
                {**event, "eventId": str(uuid4()), "impressionId": None, "makeupZone": "blush"},
                400,
            )
            await post("events", {**event, "eventId": str(uuid4()), "eventType": "cart_add"})
            await post("events", {**event, "eventId": str(uuid4()), "impressionId": None})
            warm = await post("palette", {"makeupZone": "lip"})
            assert warm["preferences"] == [{"productId": pid, "shadeId": sid, "weight": 3}]
            assert not (await post("palette", {"makeupZone": "blush"}))["preferences"]
            actor = other
            assert (await post("palette", {"makeupZone": "lip"}))["preferences"] == [
                {"productId": pid, "shadeId": sid, "weight": 1}
            ]
            await post("impressions", exposure, 404)
            await post("events", event, 404)
        result = (
            await conn.execute(
                text(
                    "SELECT count(*), count(impression_id) FROM ar_activity_events "
                    "WHERE member_id=:owner"
                ),
                {"owner": owner},
            )
        ).one()
        assert tuple(result) == (3, 2)

    async def verify():
        engine = create_async_engine(os.environ["AR_HISTORY_TEST_URL"])
        try:
            async with engine.connect() as conn, conn.begin() as tx:
                await run(conn)
                await tx.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("AR_HISTORY_TEST_URL"), reason="needs migrated PostgreSQL")
def test_server_rank_through_cart_produces_a_mature_training_label(monkeypatch, tmp_path):
    from datetime import timedelta

    from app.core.ar_palette import FEATURES
    from app.core.ar_palette_artifacts import read_json
    from app.repositories.ar_palette_repository import ArPaletteDatasetRepository
    from app.services.ar_palette_service import experiment_arm

    owner = "ar-rank-" + uuid4().hex
    settings = get_settings()
    monkeypatch.setattr(settings, "ar_palette_mode", "experiment")
    monkeypatch.setattr(settings, "ar_palette_experiment", "ar-smoke")
    monkeypatch.setattr(settings, "ar_palette_model_dir", None)
    monkeypatch.setattr(settings, "ar_palette_data_dir", tmp_path)
    app = create_app()
    app.dependency_overrides[require_user] = lambda: AuthUser(id=owner, email=None)

    async def verify():
        engine = create_async_engine(os.environ["AR_HISTORY_TEST_URL"])
        try:
            async with engine.connect() as conn, conn.begin() as transaction:
                await run(conn)
                await transaction.rollback()
        finally:
            await engine.dispose()

    async def run(conn):
        async def sessions():
            async with AsyncSession(conn, join_transaction_mode="create_savepoint") as db:
                yield db

        app.dependency_overrides[get_session] = sessions
        await conn.execute(
            text(
                "INSERT INTO members (id,terms_version,terms_agreed_at,"
                "skin_subscription_until) VALUES "
                "(:o,:v,now()-interval '1 day',now()+interval '1 day')"
            ),
            {"o": owner, "v": TERMS_VERSION},
        )
        pairs = (
            await conn.execute(
                text("""
                SELECT DISTINCT ON (p.id) p.id, s.id
                FROM products p JOIN shades s ON s.product_id = p.id
                JOIN raw_oy_review_summary r ON p.id = 'oy-' || lower(r.goods_no)
                WHERE p.makeup_zone = 'lip' AND p.texture IS NOT NULL
                  AND r.collected_at IS NOT NULL AND r.review_count > 0
                  AND r.rating_avg BETWEEN 1 AND 5 AND s.hex ~ '^#[0-9a-fA-F]{6}$'
                  AND coalesce(s.measure_method, '') <> 'placeholder'
                  AND coalesce(s.color_source, '') <> 'placeholder'
                ORDER BY p.id, s.id LIMIT 4
            """)
            )
        ).all()
        assert len(pairs) == 4
        session, request_id = str(uuid4()), str(uuid4())
        request = {
            "sessionId": session,
            "requestId": request_id,
            "makeupZone": "lip",
            "shades": [{"productId": p, "shadeId": s} for p, s in pairs],
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/me/ar-history/"
        ) as client:

            async def post(name, payload):
                res = await client.post(name, json=payload)
                assert res.status_code == 200, res.text
                return res.json()

            assert (await post("status", {}))["serverRanking"]
            decision = await post("rank", request)
            assert await post("rank", request) == decision
            assert len(decision["candidates"]) == 3
            candidate = decision["candidates"][0]
            snapshot = read_json(tmp_path / "snapshots" / f"{request_id}.json")
            assert set(snapshot["features"][candidate["candidateId"]]) == set(FEATURES)
            imp = str(uuid4())
            await post(
                "impressions",
                {
                    "impressionId": imp,
                    "candidateId": candidate["candidateId"],
                    "viewInstanceId": str(uuid4()),
                    "displayedPosition": 1,
                    "occurredAt": datetime.now(UTC).isoformat(),
                    "visibilityPolicyVersion": "direct-interaction-v1",
                },
            )
            now = datetime.now(UTC)
            event = {
                "impressionId": imp,
                "sessionId": session,
                "makeupZone": "lip",
                "productId": candidate["productId"],
                "shadeId": candidate["shadeId"],
                "occurredAt": now.isoformat(),
                "eventType": "cart_add",
            }
            for _ in range(2):
                await post("events", {**event, "eventId": str(uuid4())})
        async with AsyncSession(conn, join_transaction_mode="create_savepoint") as db:
            repository = ArPaletteDatasetRepository(db)
            options = dict(
                window=timedelta(days=1),
                grace=timedelta(days=1),
                terms=TERMS_VERSION,
            )
            assert not [
                r
                async for r in repository.exposures(as_of=now, **options)
                if r["member_id"] == owner
            ]
            mature = [
                r
                async for r in repository.exposures(as_of=now + timedelta(days=3), **options)
                if r["member_id"] == owner
            ]
            experiment = await repository.experiment_sessions(
                experiment="ar-smoke",
                start=now - timedelta(hours=1),
                end=now + timedelta(hours=1),
                as_of=now + timedelta(days=3),
                **options,
            )
        assert [(str(r["impression_id"]), r["added_to_cart"]) for r in mature] == [(imp, True)]
        assert len(experiment) == 1
        row = experiment[0]
        assert row["arm"] == experiment_arm("ar-smoke", owner)
        assert row["added_to_cart"] and row["fallback"] == (row["arm"] == "B")

    asyncio.run(verify())
