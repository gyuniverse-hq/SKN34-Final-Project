import time
from types import SimpleNamespace

import anyio
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import auth
from app.core.errors import ApiError

GUEST = {"X-Vishue-Anonymous-Id": "guest-session-id-0123456789-abcdefghijk"}


@pytest.mark.parametrize("header", ["Bearer bad", "Basic bad", "Bearer", ""])
def test_bad_authorization_never_falls_back_to_guest(client, header):
    headers = {**GUEST, "Authorization": header}
    response = client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (401, "unauthorized")


def test_unconfigured_auth_only_blocks_requests_with_bearer(client, monkeypatch):
    monkeypatch.setattr(auth, "get_verifier", lambda: None)
    assert client.post("/api/chat", json={"message": "hi"}, headers=GUEST).status_code == 200
    response = client.post(
        "/api/chat", json={"message": "hi"}, headers={**GUEST, "Authorization": "Bearer token"}
    )
    assert (response.status_code, response.json()["code"]) == (503, "auth_unavailable")
    assert client.get("/api/chat/conversations", headers=GUEST).status_code == 401


def test_auth_service_outage_does_not_fall_back_to_guest(client, monkeypatch):
    class UnavailableVerifier:
        async def verify(self, token):
            raise ApiError(503, "Authentication is unavailable", "auth_unavailable")

    monkeypatch.setattr(auth, "get_verifier", lambda: UnavailableVerifier())
    response = client.post(
        "/api/chat", json={"message": "hi"}, headers={**GUEST, "Authorization": "Bearer token"}
    )
    assert (response.status_code, response.json()["code"]) == (503, "auth_unavailable")


def test_valid_user_and_guest_have_separate_principals(client):
    assert client.post("/api/chat", json={"message": "hi"}, headers=GUEST).status_code == 200
    assert (
        client.post(
            "/api/chat", json={"message": "hi"}, headers={"Authorization": "Bearer ok-1"}
        ).status_code
        == 200
    )


def test_ack_does_not_fall_back_to_guest_on_bad_authorization(client):
    response = client.post(
        "/api/chat/acks",
        headers={**GUEST, "Authorization": "Bearer bad"},
        json={
            "requestId": "0d8b4c3e-8c41-44d2-9b27-9a8e1471a420",
            "commandId": "0d8b4c3e-8c41-44d2-9b27-9a8e1471a421",
            "sessionId": "c847eaa8-4cf9-4e97-8b5d-341d8619f852",
            "status": "APPLIED",
            "actualStateVersion": 8,
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize("status,expected", [(401, None), (403, None), (500, 503), (429, 503)])
def test_auth_server_distinguishes_invalid_token_and_outage(monkeypatch, status, expected):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(status)), **kwargs
        ),
    )
    verifier = auth.SupabaseTokenVerifier("https://example.test", "public-key")
    if expected is None:
        assert anyio.run(verifier._claims_from_auth_server, "token") is None
    else:
        with pytest.raises(ApiError) as error:
            anyio.run(verifier._claims_from_auth_server, "token")
        assert (error.value.status, error.value.code) == (503, "auth_unavailable")


def test_signed_tokens_validate_expiry_and_signature():
    key = ec.generate_private_key(ec.SECP256R1())
    other_key = ec.generate_private_key(ec.SECP256R1())
    verifier = auth.SupabaseTokenVerifier("https://example.test", "public-key")
    verifier._jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    claims = {
        "sub": "user-1",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": "https://example.test/auth/v1",
        "exp": int(time.time()) - 60,
    }
    expired = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "key-1"})
    claims["exp"] = int(time.time()) + 60
    forged = jwt.encode(claims, other_key, algorithm="ES256", headers={"kid": "key-1"})
    valid = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "key-1"})
    del claims["exp"]
    no_expiry = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "key-1"})
    assert anyio.run(verifier.verify, expired) is None
    assert anyio.run(verifier.verify, forged) is None
    assert anyio.run(verifier.verify, no_expiry) is None
    assert anyio.run(verifier.verify, valid)["sub"] == "user-1"


def test_jwks_connection_failure_is_unavailable():
    key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode({"sub": "user-1"}, key, algorithm="ES256", headers={"kid": "key-1"})
    verifier = auth.SupabaseTokenVerifier("https://example.test", "public-key")

    def fail(_token):
        raise jwt.PyJWKClientConnectionError("offline")

    verifier._jwks = SimpleNamespace(get_signing_key_from_jwt=fail)
    with pytest.raises(ApiError) as error:
        anyio.run(verifier.verify, token)
    assert (error.value.status, error.value.code) == (503, "auth_unavailable")
