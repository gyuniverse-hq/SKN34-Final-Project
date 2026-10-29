from fastapi.testclient import TestClient

from app.main import create_app


def test_result_pages_are_not_captured_as_an_order_id():
    client = TestClient(create_app())
    token = "t" * 32

    success = client.get(f"/pay/success?token={token}&orderId=o1&paymentKey=k&amount=1000")
    assert success.status_code == 200
    assert "/api/payments/confirm" in success.text

    fail = client.get("/pay/fail")
    assert fail.status_code == 200
    assert "status=failed" in fail.text
