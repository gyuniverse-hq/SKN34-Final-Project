"""Clock-skew tolerance for Supabase ES256 access tokens."""

from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import SupabaseTokenVerifier


def test_verify_accepts_token_with_future_iat_within_leeway(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "role": "authenticated",
            "email": "a@b.c",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "iat": now + timedelta(seconds=30),
            "exp": now + timedelta(hours=1),
        },
        private,
        algorithm="ES256",
        headers={"kid": "test-kid"},
    )

    class _Key:
        key = public

    class _Jwks:
        def get_signing_key_from_jwt(self, _token: str) -> _Key:
            return _Key()

    verifier = SupabaseTokenVerifier(
        "https://example.supabase.co",
        "publishable-key",
    )
    monkeypatch.setattr(verifier, "_jwks", _Jwks())

    import asyncio

    claims = asyncio.run(verifier.verify(token))
    assert claims is not None
    assert claims["sub"] == "user-1"
