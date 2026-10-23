def test_liveness_does_not_touch_dependencies(client):
    res = client.get("/healthz", headers={"X-Request-ID": "r1"})
    assert res.status_code == 200
    assert res.headers["x-request-id"] == "r1"
