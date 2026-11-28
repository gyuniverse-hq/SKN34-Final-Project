from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthUser, require_user
from app.main import create_app
from app.services.payment_service import PaymentService, get_payment_service


def test_result_pages_are_not_captured_as_an_order_id():
    client = TestClient(create_app())
    token = "t" * 32

    success = client.get(f"/pay/success?token={token}&orderId=o1&paymentKey=k&amount=1000")
    assert success.status_code == 200
    assert "/api/payments/confirm" in success.text
    assert "결제를 확인하고 있어요" in success.text

    fail = client.get("/pay/fail")
    assert fail.status_code == 200
    assert "status=failed" in fail.text
    assert "결제가 완료되지 않았어요" in fail.text
    assert "status=unknown" in success.text


def test_checkout_page_shows_order_summary_and_loading_state():
    class Orders:
        async def get(self, order_id):
            return SimpleNamespace(
                id=order_id,
                order_name="3CE 소프트 매트 립스틱",
                amount_krw=19000,
                checkout_token_hash="unused",
                status="pending",
            )

    class Service(PaymentService):
        async def checkout(self, order_id: str, token: str):
            from app.schemas.payment import PublicCheckout

            return PublicCheckout(
                order_id=order_id,
                order_name="3CE 소프트 매트 립스틱",
                amount=19000,
                checkout_token=token,
            )

    app = create_app()
    settings = SimpleNamespace(toss_client_key="test_ck")
    app.dependency_overrides[get_payment_service] = lambda: Service(Orders(), None, None, settings)
    token = "t" * 32
    page = TestClient(app).get(f"/pay/order-1?token={token}")
    assert page.status_code == 200
    assert "3CE 소프트 매트 립스틱" in page.text
    assert "19,000원" in page.text
    assert "결제 수단을 준비하고 있어요" in page.text
    assert "VISHUE" in page.text


def test_order_status_is_only_visible_to_its_owner():
    class Orders:
        async def get(self, order_id):
            if order_id == "order-1":
                return SimpleNamespace(id=order_id, user_id="owner", status="paid")
            return None

    app = create_app()
    service = PaymentService(Orders(), None, None, None)
    app.dependency_overrides[get_payment_service] = lambda: service
    app.dependency_overrides[require_user] = lambda: AuthUser(id="owner", email=None)
    client = TestClient(app)
    assert client.get("/api/payments/orders/order-1").json() == {
        "orderId": "order-1",
        "status": "paid",
    }
    assert client.get("/api/payments/orders/missing").status_code == 404
    app.dependency_overrides[require_user] = lambda: AuthUser(id="other", email=None)
    assert client.get("/api/payments/orders/order-1").status_code == 404


@pytest.mark.parametrize("stored_status", ["paid", "preparing", "shipped", "delivered"])
def test_fulfillment_keeps_mobile_payment_success_contract(stored_status):
    class Orders:
        async def get(self, order_id):
            return SimpleNamespace(id=order_id, user_id="owner", status=stored_status)

    app = create_app()
    app.dependency_overrides[get_payment_service] = lambda: PaymentService(
        Orders(), None, None, None
    )
    app.dependency_overrides[require_user] = lambda: AuthUser(id="owner", email=None)
    response = TestClient(app).get("/api/payments/orders/order-1")
    assert response.status_code == 200
    assert response.json() == {"orderId": "order-1", "status": "paid"}
