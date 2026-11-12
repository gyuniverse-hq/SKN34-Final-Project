import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.clients.toss_client import TossPaymentsClient
from app.core import auth
from app.core.cache import NullCache
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.core.errors import ApiError
from app.main import create_app
from app.models.admin import AdminAuditLogRow, ProductAdminStateRow, StaffRoleRow
from app.models.member import MemberRow
from app.repositories.admin_repository import AdminRepository
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.admin import EvalCreate
from app.services.admin_service import TRANSITIONS, check_transition, order_view
from app.services.catalog_service import CatalogService
from tests.conftest import SAMPLE

FIXTURE = Path(__file__).parent / "fixtures" / "admin_eval_v2.json"


@pytest.mark.parametrize("old", TRANSITIONS)
@pytest.mark.parametrize("new", TRANSITIONS)
def test_all_order_transitions(old, new):
    if new in TRANSITIONS[old]:
        check_transition(old, new)
    else:
        with pytest.raises(ApiError) as exc:
            check_transition(old, new)
        assert exc.value.status == 409
        assert exc.value.code == "invalid_transition"


def test_order_masking_does_not_expose_payment_key_or_member():
    value = order_view(
        SimpleNamespace(
            id="o",
            user_id="12345678-private",
            amount_krw=1,
            order_name="test",
            status="paid",
            created_at=None,
            paid_at=None,
            payment_key="abcd-secret-value",
        )
    )
    assert value["userId"] == "12345678…"
    assert value["paymentKey"] == "abcd…"
    assert "secret" not in json.dumps(value)


def test_v2_fixture_and_confidence_intervals():
    body = EvalCreate.model_validate_json(FIXTURE.read_text(encoding="utf8"))
    assert body.summary_json.factors.total.estimate == pytest.approx(3.0389473684)
    assert body.summary_json.reliability.rater_count == 5
    assert body.summary_json.mdc95 == 1.42


@pytest.mark.parametrize(
    "bad", ["C:/faces/photo.jpg", "../secret", "https://example.com", "image_id123", "x" * 1025]
)
def test_eval_rejects_sensitive_strings(bad):
    value = json.loads(FIXTURE.read_text(encoding="utf8"))
    value["summaryJson"]["finishes"][0]["label"] = bad
    with pytest.raises(ValidationError):
        EvalCreate.model_validate(value)


def test_eval_rejects_extra_image_fields():
    value = json.loads(FIXTURE.read_text(encoding="utf8"))
    value["summaryJson"]["imageId"] = "abc"
    with pytest.raises(ValidationError):
        EvalCreate.model_validate(value)


def test_toss_cancel_contract_and_failure(monkeypatch):
    requests = []

    async def post(self, url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200 if len(requests) == 1 else 500)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    async def run():
        client = TossPaymentsClient("test-secret")
        await client.cancel("key/a", "테스트 취소")
        with pytest.raises(ApiError) as exc:
            await client.cancel("key/a", "테스트 취소")
        assert exc.value.code == "payment_cancel_failed"

    asyncio.run(run())
    assert requests[0][0] == "https://api.tosspayments.com/v1/payments/key%2Fa/cancel"
    assert requests[0][1]["json"] == {"cancelReason": "테스트 취소"}
    assert (
        requests[0][1]["headers"]["Idempotency-Key"] == requests[1][1]["headers"]["Idempotency-Key"]
    )


@pytest.fixture
def admin_client(monkeypatch):
    url = os.environ.get("ADMIN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs isolated local PostgreSQL via ADMIN_TEST_DATABASE_URL")
    if make_url(url).host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("admin tests only allow local PostgreSQL")
    schema = "admin_test_" + uuid4().hex
    setup_engine = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        execution_options={"schema_translate_map": {None: schema}},
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with setup_engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            await CatalogService(CatalogRepository(session), NullCache(), 0).import_catalog(SAMPLE)
            session.add_all(
                [
                    MemberRow(id=key, terms_version="test", terms_agreed_at=datetime.now(UTC))
                    for key in ("admin", "viewer", "customer")
                ]
            )
            await session.flush()
            session.add_all(
                [
                    StaffRoleRow(user_id="admin", role="admin"),
                    StaffRoleRow(user_id="viewer", role="viewer"),
                ]
            )
            await session.commit()

    asyncio.run(setup())
    monkeypatch.setenv("ADMIN_ENABLED", "true")
    monkeypatch.setenv("TOSS_CLIENT_KEY", "test-client")
    monkeypatch.setenv("PAYMENT_WEB_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()

    class Verifier:
        async def verify(self, token):
            if token not in ("admin", "viewer", "customer"):
                return None
            return {"sub": token, "email": None, "role": "authenticated"}

    monkeypatch.setattr(auth, "get_verifier", lambda: Verifier())

    async def session_override():
        async with sessions() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    client = TestClient(app, raise_server_exceptions=False)
    yield client, sessions

    async def teardown():
        await engine.dispose()
        async with setup_engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await setup_engine.dispose()

    asyncio.run(teardown())
    get_settings.cache_clear()


def test_staff_authorization_and_no_self_grant(admin_client):
    client, _ = admin_client
    assert client.get("/api/admin/me").status_code == 401
    assert (
        client.get("/api/admin/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    )
    assert (
        client.get("/api/admin/me", headers={"Authorization": "Bearer customer"}).status_code == 403
    )
    assert (
        client.get("/api/admin/me", headers={"Authorization": "Bearer viewer"}).json()["role"]
        == "viewer"
    )
    assert (
        client.patch(
            "/api/admin/products/lip-1/admin-state",
            json={"stock": 1},
            headers={"Authorization": "Bearer viewer"},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/admin/audit-log", headers={"Authorization": "Bearer viewer"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/admin/staff-roles",
            json={"role": "admin"},
            headers={"Authorization": "Bearer customer"},
        ).status_code
        == 404
    )


def test_inventory_payment_cancel_seed_and_audit_atomicity(admin_client, monkeypatch):
    client, sessions = admin_client
    headers = {"Authorization": "Bearer admin", "X-Request-ID": "admin-test"}

    async def approve(*args):
        pass

    monkeypatch.setattr(TossPaymentsClient, "approve", approve)
    monkeypatch.setattr(TossPaymentsClient, "cancel", approve)
    assert (
        client.patch(
            "/api/admin/products/lip-1/admin-state", json={"stock": 2}, headers=headers
        ).status_code
        == 200
    )
    body = {"lines": [{"productId": "lip-1", "quantity": 3}]}
    assert client.post("/api/payments/orders", json=body, headers=headers).status_code == 409
    body["lines"][0]["quantity"] = 2
    created = client.post("/api/payments/orders", json=body, headers=headers).json()
    from urllib.parse import parse_qs, urlsplit

    token = parse_qs(urlsplit(created["checkoutUrl"]).query)["token"][0]
    payment = {
        "orderId": created["orderId"],
        "amount": created["amount"],
        "checkoutToken": token,
        "paymentKey": "test-payment-key",
    }
    assert client.post("/api/payments/confirm", json=payment).status_code == 200
    assert client.post("/api/payments/confirm", json=payment).status_code == 200
    assert client.get("/api/admin/products/lip-1", headers=headers).json()["stock"] == 0

    async def fail(*args):
        raise ApiError(502, "cancel failed", "payment_cancel_failed")

    monkeypatch.setattr(TossPaymentsClient, "cancel", fail)
    endpoint = f"/api/admin/orders/{created['orderId']}/status"
    assert (
        client.post(
            endpoint, json={"status": "canceled", "reason": "테스트"}, headers=headers
        ).status_code
        == 502
    )
    assert (
        client.get(f"/api/admin/orders/{created['orderId']}", headers=headers).json()["status"]
        == "paid"
    )
    monkeypatch.setattr(TossPaymentsClient, "cancel", approve)
    assert (
        client.post(
            endpoint, json={"status": "canceled", "reason": "테스트"}, headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            endpoint, json={"status": "canceled", "reason": "테스트"}, headers=headers
        ).status_code
        == 409
    )
    assert client.get("/api/admin/products/lip-1", headers=headers).json()["stock"] == 2
    assert (
        client.patch(
            "/api/admin/products/lip-1/admin-state", json={"isVisible": False}, headers=headers
        ).status_code
        == 200
    )
    assert client.get("/api/products/lip-1").status_code == 404
    assert "lip-1" not in [p["id"] for p in client.get("/api/products").json()["products"]]

    async def seed():
        async with sessions() as session:
            await CatalogService(CatalogRepository(session), NullCache(), 0).import_catalog(SAMPLE)
            state = await session.get(ProductAdminStateRow, "lip-1")
            assert state.stock == 2 and state.is_visible is False

    asyncio.run(seed())
    original_audit = AdminRepository.audit

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AdminRepository, "audit", fail_audit)
    assert (
        client.patch(
            "/api/admin/products/lip-1/admin-state", json={"stock": 99}, headers=headers
        ).status_code
        == 500
    )
    monkeypatch.setattr(AdminRepository, "audit", original_audit)
    assert client.get("/api/admin/products/lip-1", headers=headers).json()["stock"] == 2
    log = client.get("/api/admin/audit-log?limit=1", headers=headers).json()
    assert log["items"][0]["requestId"] == "admin-test"
    assert log["nextCursor"]
    assert client.get("/api/admin/audit-log?cursor=bad", headers=headers).status_code == 400


def test_eval_publish_idempotent_and_audited(admin_client):
    client, sessions = admin_client
    headers = {"Authorization": "Bearer admin"}
    body = json.loads(FIXTURE.read_text(encoding="utf8"))
    first = client.post("/api/admin/eval-runs", json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = client.post("/api/admin/eval-runs", json=body, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/admin/eval-runs", headers=headers).json()["items"]) == 1

    async def check():
        async with sessions() as session:
            logs = list(
                await session.scalars(
                    select(AdminAuditLogRow).where(AdminAuditLogRow.action == "eval_publish")
                )
            )
            assert len(logs) == 1

    asyncio.run(check())


def test_concurrent_confirm_cannot_oversell_or_duplicate_purchase(admin_client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import parse_qs, urlsplit

    from app.models.recommendation_feedback import UserBehaviorEventRow

    client, sessions = admin_client
    headers = {"Authorization": "Bearer admin"}
    approvals = []

    async def approve(self, key, order_id, amount):
        approvals.append(order_id)
        await asyncio.sleep(0.02)

    monkeypatch.setattr(TossPaymentsClient, "approve", approve)
    assert (
        client.patch(
            "/api/admin/products/lip-1/admin-state", json={"stock": 2}, headers=headers
        ).status_code
        == 200
    )
    payments = []
    for index in range(2):
        created = client.post(
            "/api/payments/orders",
            json={"lines": [{"productId": "lip-1", "quantity": 2}]},
            headers=headers,
        ).json()
        payments.append(
            {
                "orderId": created["orderId"],
                "amount": created["amount"],
                "checkoutToken": parse_qs(urlsplit(created["checkoutUrl"]).query)["token"][0],
                "paymentKey": f"payment-{index}",
            }
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda body: client.post("/api/payments/confirm", json=body), payments)
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(approvals) == 1
    assert client.get("/api/admin/products/lip-1", headers=headers).json()["stock"] == 0

    async def check():
        async with sessions() as session:
            assert len(list(await session.scalars(select(UserBehaviorEventRow)))) == 1

    asyncio.run(check())
