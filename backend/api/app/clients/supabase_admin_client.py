from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import ApiError


class AccountDeleter(Protocol):
    async def delete_user(self, user_id: str) -> None: ...


class SupabaseAdminClient:
    """Supabase Auth admin API. The only place the Supabase secret key is used."""

    def __init__(
        self,
        supabase_url: str | None,
        secret_key: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth_url = f"{supabase_url.rstrip('/')}/auth/v1" if supabase_url else None
        self._secret_key = secret_key
        self._transport = transport

    async def delete_user(self, user_id: str) -> None:
        """Deletes the Supabase account. An account that is already gone counts as deleted."""
        if not (self._auth_url and self._secret_key):
            raise ApiError(
                503, "Account deletion is not configured", "account_deletion_unavailable"
            )
        headers = {"apikey": self._secret_key}
        # Secret keys (sb_secret_...) are not JWTs and must not be sent as a bearer token;
        # a legacy service_role key is a JWT and needs it.
        if self._secret_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self._secret_key}"
        url = f"{self._auth_url}/admin/users/{quote(user_id, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
                response = await client.delete(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ApiError(502, "Account service is unavailable", "account_upstream") from exc
        if response.status_code == 404:
            return
        if response.status_code >= 400:
            raise ApiError(502, "Account deletion failed", "account_deletion_failed")
