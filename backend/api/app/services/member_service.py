from datetime import UTC, datetime
from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.supabase_admin_client import AccountDeleter, SupabaseAdminClient
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberRecord, MeResponse, TermsStatus

# Same value as TERMS_VERSION in the app's constants/legal.ts. Bump both when the terms change.
TERMS_VERSION = "2026-10-30"


class MemberStore(Protocol):
    async def get(self, member_id: str) -> MemberRecord | None: ...
    async def save_terms(
        self, member_id: str, version: str, agreed_at: datetime
    ) -> MemberRecord: ...
    async def delete(self, member_id: str) -> None: ...


def _terms(member: MemberRecord | None) -> TermsStatus:
    return TermsStatus(
        version=TERMS_VERSION,
        agreed_version=member.terms_version if member else None,
        agreed_at=member.terms_agreed_at if member else None,
    )


class MemberService:
    def __init__(self, members: MemberStore, accounts: AccountDeleter) -> None:
        self._members, self._accounts = members, accounts

    async def me(self, user: AuthUser) -> MeResponse:
        return MeResponse(user=user, terms=_terms(await self._members.get(user.id)))

    async def agree_terms(self, user: AuthUser, version: str) -> TermsStatus:
        if version != TERMS_VERSION:
            raise ApiError(409, "The terms have changed", "terms_outdated")
        return _terms(await self._members.save_terms(user.id, version, datetime.now(UTC)))

    async def delete_account(self, user: AuthUser) -> None:
        """Deletes the Supabase account first, so a failure leaves everything in place to retry.

        Orders are kept: commerce records must be retained by law and hold no account data.
        """
        await self._accounts.delete_user(user.id)
        await self._members.delete(user.id)


def get_member_service(session: AsyncSession = Depends(get_session)) -> MemberService:
    settings = get_settings()
    return MemberService(
        MemberRepository(session),
        SupabaseAdminClient(settings.supabase_url, settings.supabase_secret_key),
    )
