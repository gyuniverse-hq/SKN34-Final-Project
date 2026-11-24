"""Call the local chatbot deletion endpoint with G7's versioned request signature."""

import asyncio
import hmac
import json
import time
from secrets import token_hex
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError

_PATH = "/internal/g7/account-deletion"
_DEADLINE_SECONDS = 15.0


def _unavailable() -> ApiError:
    return ApiError(503, "Internal chatbot deletion is unavailable", "account_deletion_unavailable")


def _incomplete() -> ApiError:
    return ApiError(503, "Chatbot cleanup is unconfirmed", "account_deletion_incomplete")


async def delete_chatbot_account(job_id: UUID, owner_id: str) -> None:
    settings = get_settings()
    if settings.env not in {"local", "test"} or settings.g7_internal_deletion_key is None:
        raise _unavailable()
    key = settings.g7_internal_deletion_key.get_secret_value().encode("utf-8")
    try:
        origin = httpx.URL(settings.g7_chatbot_deletion_base_url or "")
    except httpx.InvalidURL:
        raise _unavailable() from None
    if (
        len(key) < 32
        or origin.scheme not in {"http", "https"}
        or origin.host not in {"127.0.0.1", "::1"}
        or origin.userinfo
        or origin.raw_path != b"/"
        or origin.fragment
    ):
        raise _unavailable()

    body = json.dumps({"jobId": str(job_id), "ownerId": owner_id}, separators=(",", ":")).encode()
    issued_at, nonce = str(int(time.time())), token_hex(16)
    # The verifier signs these same fields and the exact bytes sent on the wire.
    prefix = f"vishue:g7:account-deletion:v1\nPOST\n{_PATH}\n{issued_at}\n{nonce}\n".encode()
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": str(job_id),
        "X-G7-Deletion-Timestamp": issued_at,
        "X-G7-Deletion-Nonce": nonce,
        "X-G7-Deletion-Signature": hmac.digest(key, prefix + body, "sha256").hex(),
    }
    try:
        async with (
            asyncio.timeout(_DEADLINE_SECONDS),
            httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(_DEADLINE_SECONDS, connect=2.0),
            ) as client,
            client.stream(
                "POST", origin.copy_with(path=_PATH), content=body, headers=headers
            ) as response,
        ):
            if response.status_code != 204:
                raise _incomplete()
    except (httpx.RequestError, TimeoutError) as exc:
        raise _incomplete() from exc
