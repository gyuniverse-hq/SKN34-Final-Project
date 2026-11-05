"""Real JWT signatures, no Supabase network or user credentials."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from server.nia.auth import AuthUnavailable, SupabaseTokenVerifier

ISSUER = "https://project.supabase.co/auth/v1"


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(**overrides):
    return {
        "sub": "signed-in-user",
        "iss": ISSUER,
        "aud": "authenticated",
        "exp": int(time.time()) + 600,
        "role": "authenticated",
        **overrides,
    }


def verifier(private_key):
    value = SupabaseTokenVerifier("https://project.supabase.co", "public-key")
    value.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=private_key.public_key())
    )
    return value


def test_valid_user_signature(private_key):
    token = jwt.encode(claims(), private_key, algorithm="RS256", headers={"kid": "test"})
    assert asyncio.run(verifier(private_key).verify(token))["sub"] == "signed-in-user"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},
        {"iss": "https://another-project.supabase.co/auth/v1"},
        {"aud": "other"},
        {"role": "anon"},
        {"role": "service_role"},
        {"sub": ""},
        {"is_anonymous": True},
        {"exp": None},
    ],
)
def test_wrong_claims_are_rejected(private_key, overrides):
    token = jwt.encode(claims(**overrides), private_key, algorithm="RS256")
    assert asyncio.run(verifier(private_key).verify(token)) is None


def test_forged_signature_is_rejected(private_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(claims(), other, algorithm="RS256")
    assert asyncio.run(verifier(private_key).verify(token)) is None


@pytest.mark.parametrize("token", ["not-a-token", jwt.encode(claims(), key="", algorithm="none")])
def test_unsigned_or_malformed_token_is_rejected(private_key, token):
    assert asyncio.run(verifier(private_key).verify(token)) is None


def test_signing_key_network_failure_is_not_treated_as_a_valid_user(private_key):
    value = verifier(private_key)
    value.jwks.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("offline")
    token = jwt.encode(claims(), private_key, algorithm="RS256")
    with pytest.raises(AuthUnavailable):
        asyncio.run(value.verify(token))


@pytest.mark.parametrize("status,accepted", [(200, True), (401, False), (403, False)])
def test_legacy_hs256_uses_supabase_user_verification(monkeypatch, status, accepted):
    response = Mock(status_code=status)
    response.json.return_value = {"id": "signed-in-user", "role": "authenticated"}
    client = Mock(get=AsyncMock(return_value=response))
    context = Mock(
        __aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock(return_value=False)
    )
    monkeypatch.setattr("server.nia.auth.httpx.AsyncClient", Mock(return_value=context))
    token = jwt.encode(claims(), "fixture-only-legacy-secret-32-characters", algorithm="HS256")
    value = SupabaseTokenVerifier("https://project.supabase.co", "public-key")
    result = asyncio.run(value.verify(token))
    assert (result is not None) is accepted
    client.get.assert_awaited_once_with(
        ISSUER + "/user",
        headers={
            "apikey": "public-key",
            "Authorization": "Bearer " + token,
        },
    )


def test_legacy_auth_outage_fails_closed(monkeypatch):
    client = Mock(get=AsyncMock(side_effect=httpx.ConnectError("offline")))
    context = Mock(
        __aenter__=AsyncMock(return_value=client), __aexit__=AsyncMock(return_value=False)
    )
    monkeypatch.setattr("server.nia.auth.httpx.AsyncClient", Mock(return_value=context))
    token = jwt.encode(claims(), "fixture-only-legacy-secret-32-characters", algorithm="HS256")
    with pytest.raises(AuthUnavailable):
        asyncio.run(
            SupabaseTokenVerifier("https://project.supabase.co", "public-key").verify(token)
        )
