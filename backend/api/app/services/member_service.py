from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.supabase_admin_client import AccountDeleter, SupabaseAdminClient
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.member_repository import MemberRepository
from app.schemas.member import ConsentKind, MemberRecord, MeResponse, SkinAccess, TermsStatus

# Same value as TERMS_VERSION in the app's constants/legal.ts. Bump both when the terms change.
TERMS_VERSION = "2026-11-25"


class MemberStore(Protocol):
    async def get(self, member_id: str) -> MemberRecord | None: ...
    async def save_terms(
        self,
        member_id: str,
        version: str,
        agreed_at: datetime,
        ar_consent: bool | None,
        camera_consent: bool | None,
    ) -> MemberRecord: ...
    async def set_consent(
        self, member_id: str, kind: ConsentKind, enabled: bool
    ) -> MemberRecord | None: ...
    async def claim_first_ar_visit(self, member_id: str) -> bool: ...
    async def complete_analysis(self, member_id: str, run_id: str) -> MemberRecord | None: ...
    async def set_skin_subscription(
        self, member_id: str, until: datetime
    ) -> MemberRecord | None: ...
    async def delete(self, member_id: str) -> None: ...


def _skin_access(member: MemberRecord | None) -> SkinAccess:
    return SkinAccess(
        expires_at=member.skin_subscription_until if member else None,
        subscribed=bool(
            member
            and member.skin_subscription_until
            and member.skin_subscription_until > datetime.now(UTC)
        ),
        trial_used=bool(member and member.skin_trial_run),
    )


def _terms(member: MemberRecord | None) -> TermsStatus:
    return TermsStatus(
        version=TERMS_VERSION,
        camera_features_consent=member.camera_features_consent if member else None,
        ar_activity_consent=bool(member and member.ar_activity_consented_at),
        agreed_version=member.terms_version if member else None,
        agreed_at=member.terms_agreed_at if member else None,
    )


class MemberService:
    def __init__(self, members: MemberStore, accounts: AccountDeleter) -> None:
        self._members, self._accounts = members, accounts

    async def me(self, user: AuthUser) -> MeResponse:
        return MeResponse(user=user, terms=_terms(await self._members.get(user.id)))

    async def first_ar_visit(self, user: AuthUser) -> bool:
        return await self._members.claim_first_ar_visit(user.id)

    async def skin_access(self, user: AuthUser) -> SkinAccess:
        return _skin_access(await self._members.get(user.id))

    async def complete_analysis(self, user: AuthUser, run_id: str) -> SkinAccess:
        member = await self._members.complete_analysis(user.id, run_id)
        if member is None:
            raise ApiError(409, "Analysis requires an active membership", "skin_access_required")
        return _skin_access(member)

    async def start_dev_subscription(self, user: AuthUser) -> SkinAccess:
        if get_settings().env not in {"local", "development", "test"}:
            raise ApiError(404, "Not found", "not_found")
        member = await self._members.set_skin_subscription(
            user.id, datetime.now(UTC) + timedelta(days=30)
        )
        if member is None:
            raise ApiError(409, "Agree to the terms first", "terms_required")
        return _skin_access(member)

    async def agree_terms(
        self,
        user: AuthUser,
        version: str,
        ar_consent: bool | None = None,
        camera_consent: bool | None = None,
    ) -> TermsStatus:
        if version != TERMS_VERSION:
            raise ApiError(409, "The terms have changed", "terms_outdated")
        return _terms(
            await self._members.save_terms(
                user.id, version, datetime.now(UTC), ar_consent, camera_consent
            )
        )

    async def set_consent(self, user: AuthUser, kind: ConsentKind, enabled: bool) -> TermsStatus:
        member = await self._members.set_consent(user.id, kind, enabled)
        if member is None:
            raise ApiError(409, "Agree to the terms first", "terms_required")
        return _terms(member)

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
