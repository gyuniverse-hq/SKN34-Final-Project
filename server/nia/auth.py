"""Verify user access tokens without coupling GPU inference to another service."""

import hmac

import anyio
import httpx
import jwt


class TestTokenVerifier:
    """Constant-time shared-token verifier for a deliberately temporary test setup."""

    def __init__(self, token: str):
        if len(token.encode("utf-8")) < 32:
            raise ValueError("Test bearer token must contain at least 32 bytes")
        self._token = token

    async def verify(self, token: str) -> dict | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return {"sub": "shared-test-client", "role": "authenticated", "auth_mode": "test-token"}


class AuthUnavailable(RuntimeError):
    pass


class SupabaseTokenVerifier:
    def __init__(self, url: str, publishable_key: str):
        self.issuer = url.rstrip("/") + "/auth/v1"
        self.publishable_key = publishable_key
        self.jwks = jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", lifespan=600, timeout=5)

    async def verify(self, token: str) -> dict | None:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
            if algorithm in {"RS256", "ES256"}:
                key = await anyio.to_thread.run_sync(self.jwks.get_signing_key_from_jwt, token)
                claims = jwt.decode(
                    token,
                    key.key,
                    algorithms=[algorithm],
                    issuer=self.issuer,
                    audience="authenticated",
                    options={"require": ["exp", "iss", "aud", "sub"]},
                )
            elif algorithm == "HS256":
                # The legacy signing secret is never distributed to this service.
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(
                        self.issuer + "/user",
                        headers={
                            "apikey": self.publishable_key,
                            "Authorization": f"Bearer {token}",
                        },
                    )
                if response.status_code in {401, 403}:
                    return None
                if response.status_code != 200:
                    raise AuthUnavailable("Supabase Auth is unavailable")
                user = response.json()
                # Also restrict the verified token to this project's issuer/audience/lifetime.
                claims = jwt.decode(
                    token,
                    options={
                        "verify_signature": False,
                        "verify_exp": True,
                        "verify_aud": True,
                        "verify_iss": True,
                        "require": ["exp", "iss", "aud", "sub"],
                    },
                    audience="authenticated",
                    issuer=self.issuer,
                )
                if claims.get("sub") != user.get("id") or user.get("role") != "authenticated":
                    return None
            else:
                return None
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailable("Signing keys are unavailable") from exc
        except (httpx.HTTPError, ValueError) as exc:
            # Reject token errors; fail closed on transport or invalid Auth-server responses.
            if isinstance(exc, jwt.PyJWTError):
                return None
            raise AuthUnavailable("Supabase Auth is unavailable") from exc
        except jwt.PyJWTError:
            return None
        if (
            not isinstance(claims.get("sub"), str)
            or not claims["sub"]
            or claims.get("role") != "authenticated"
            or claims.get("is_anonymous") is True
        ):
            return None
        return claims
