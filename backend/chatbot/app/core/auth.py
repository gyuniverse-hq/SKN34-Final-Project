import re
from functools import lru_cache
from hashlib import sha256
from typing import Any

import anyio
import httpx
import jwt
from fastapi import Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import ApiError

_BEARER = re.compile(r"^Bearer\s+(\S+)\s*$", re.IGNORECASE)
_ASYMMETRIC = {"RS256", "ES256"}
_ANONYMOUS_ID = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class AuthUser(BaseModel):
    id: str
    email: str | None


class ChatPrincipal(BaseModel):
    """Authenticated user or non-identifying guest used solely for rate limiting."""

    rate_limit_key: str
    user: AuthUser | None = None


def bearer_token(header: str | None) -> str | None:
    match = _BEARER.match(header or "")
    return match.group(1) if match else None


def user_from_claims(claims: dict[str, Any]) -> AuthUser | None:
    if not isinstance(claims.get("sub"), str) or claims.get("role") != "authenticated":
        return None
    email = claims.get("email")
    return AuthUser(id=claims["sub"], email=email if isinstance(email, str) else None)


class SupabaseTokenVerifier:
    """Verifies Supabase access tokens locally with the project's JWKS (asymmetric signing keys).

    Projects still on the legacy shared secret (HS256) fall back to asking Supabase Auth,
    the same strategy supabase-js `getClaims()` uses in the Expo API routes.
    """

    def __init__(self, supabase_url: str, publishable_key: str) -> None:
        base = supabase_url.rstrip("/")
        self._auth_url = f"{base}/auth/v1"
        self._publishable_key = publishable_key
        self._jwks = jwt.PyJWKClient(f"{self._auth_url}/.well-known/jwks.json", lifespan=600)

    async def verify(self, token: str) -> dict[str, Any] | None:
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError:
            return None
        if alg in _ASYMMETRIC:
            try:
                key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
                return jwt.decode(
                    token,
                    key.key,
                    algorithms=[alg],
                    audience="authenticated",
                    issuer=self._auth_url,
                )
            except jwt.PyJWTError:
                return None
        return await self._claims_from_auth_server(token)

    async def _claims_from_auth_server(self, token: str) -> dict[str, Any] | None:
        headers = {"apikey": self._publishable_key, "Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                res = await client.get(f"{self._auth_url}/user", headers=headers)
        except httpx.HTTPError:
            return None
        if res.status_code != 200:
            return None
        user = res.json()
        return {"sub": user.get("id"), "email": user.get("email"), "role": user.get("role")}


@lru_cache
def get_verifier() -> SupabaseTokenVerifier | None:
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_publishable_key):
        return None
    return SupabaseTokenVerifier(settings.supabase_url, settings.supabase_publishable_key)


async def require_user(request: Request) -> AuthUser:
    """FastAPI dependency for routes that need a signed-in user."""
    verifier = get_verifier()
    if verifier is None:
        raise ApiError(503, "Login is not configured", "auth_unavailable")
    token = bearer_token(request.headers.get("authorization"))
    claims = await verifier.verify(token) if token else None
    user = user_from_claims(claims) if claims else None
    if user is None:
        raise ApiError(401, "Sign in required", "unauthorized")
    return user


async def chat_principal(request: Request) -> ChatPrincipal:
    """Accept signed-in chat users and guests with a random device-local session ID.

    Guest IDs are validated then hashed before reaching the rate limiter; no guest identifier,
    account data, or conversation history is persisted by this dependency.
    """
    token = bearer_token(request.headers.get("authorization"))
    verifier = get_verifier()
    claims = await verifier.verify(token) if verifier is not None and token else None
    user = user_from_claims(claims) if claims else None
    if user is not None:
        return ChatPrincipal(rate_limit_key=f"user:{user.id}", user=user)

    anonymous_id = request.headers.get("x-vishue-anonymous-id", "")
    if not _ANONYMOUS_ID.fullmatch(anonymous_id):
        raise ApiError(400, "Anonymous session is required", "invalid_request")
    return ChatPrincipal(rate_limit_key=f"guest:{sha256(anonymous_id.encode('ascii')).hexdigest()}")
