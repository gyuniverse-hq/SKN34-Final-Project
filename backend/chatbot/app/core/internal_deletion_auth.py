"""Verify the local API's signed deletion request before invoking the deletion service."""

import asyncio
import hmac
import re
import time

from fastapi import Request
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ratelimit import get_redis

DELETION_PATH = "/internal/g7/account-deletion"
_CLOCK_WINDOW_SECONDS = 60
_MAX_BODY_BYTES = 1024


def _forbidden() -> ApiError:
    return ApiError(403, "Internal deletion access denied", "account_deletion_forbidden")


def _unavailable() -> ApiError:
    return ApiError(
        503, "Internal deletion authentication unavailable", "account_deletion_auth_unavailable"
    )


def _signed_header(request: Request, name: str, pattern: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not re.fullmatch(pattern, values[0]):
        raise _forbidden()
    return values[0]


async def authenticate_deletion_request(request: Request) -> bytes:
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.scope["path"] != DELETION_PATH
        or request.scope["query_string"]
    ):
        raise _forbidden()
    secret = get_settings().g7_internal_deletion_key
    key = secret.get_secret_value().encode("utf-8") if secret is not None else b""
    if len(key) < 32:
        raise _unavailable()

    issued_at = _signed_header(request, "x-g7-deletion-timestamp", r"[1-9][0-9]{0,10}")
    nonce = _signed_header(request, "x-g7-deletion-nonce", r"[0-9a-f]{32}")
    signature = _signed_header(request, "x-g7-deletion-signature", r"[0-9a-f]{64}")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            raise ApiError(413, "Internal deletion payload too large", "invalid_request")
        body.extend(chunk)
    raw_body = bytes(body)

    if abs(int(time.time()) - int(issued_at)) > _CLOCK_WINDOW_SECONDS:
        raise _forbidden()
    prefix = (
        f"vishue:g7:account-deletion:v1\n{request.method}\n{DELETION_PATH}\n{issued_at}\n{nonce}\n"
    ).encode()
    expected = hmac.digest(key, prefix + raw_body, "sha256").hex()
    if not hmac.compare_digest(signature, expected):
        raise _forbidden()

    try:
        redis = get_redis()
        if redis is None:
            raise _unavailable()
        async with asyncio.timeout(2):
            # Cover the full validity window even if the sender's clock is ahead.
            claimed = await redis.set(
                f"vishue:g7:deletion-auth:{nonce}", "1", nx=True, ex=2 * _CLOCK_WINDOW_SECONDS + 1
            )
    except (RedisError, OSError, ValueError) as exc:
        raise _unavailable() from exc
    if claimed is not True:
        raise _forbidden()
    return raw_body
