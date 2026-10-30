from types import SimpleNamespace

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

    fail = client.get("/pay/fail")
    assert fail.status_code == 200
    assert "status=failed" in fail.text
    assert "status=unknown" in success.text


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
