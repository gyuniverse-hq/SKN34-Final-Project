"""Durable deletion requests and replay-safe local processing steps."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import httpx
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.chatbot_deletion_client import delete_chatbot_account
from app.clients.supabase_admin_client import AccountDeleter, SupabaseAdminClient
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import ApiError
from app.repositories.account_deletion_repository import AccountDeletionRepository
from app.repositories.member_repository import MemberRepository

_PHASES = ("BLOCKING", "PURGING_CHAT", "DELETING_AUTH", "DELETING_MEMBER")


def _unavailable() -> ApiError:
    return ApiError(503, "Account deletion is unavailable", "account_deletion_unavailable")


def _require_local_database(database_url: str) -> None:
    try:
        url = make_url(database_url)
    except SQLAlchemyError:
        raise _unavailable() from None
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "::1", "localhost"}
        or url.query
    ):
        raise _unavailable()


class AccountDeletionRequests:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, owner_id: str) -> bool:
        """Return True for completed G7 work, False for a database still on legacy deletion."""
        settings = get_settings()
        if settings.env not in {"local", "test"}:
            raise _unavailable()
        enabled = settings.g7_account_deletion_enabled
        if enabled:
            _require_local_database(settings.database_url)
        jobs = AccountDeletionRepository(self._session)
        try:
            async with self._session.begin():
                await jobs.lock_owner(owner_id)
                if not enabled and not await jobs.is_installed():
                    return False
                status = await jobs.status(owner_id)
                if status is None:
                    if enabled:
                        status = (await jobs.get_or_create(owner_id)).status
                    elif await jobs.has_jobs():
                        # Pausing intake must not route an adopted database through legacy deletion.
                        raise _unavailable()
                    else:
                        return False
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

        if status != "DONE":
            raise ApiError(409, "Account deletion is in progress", "account_deletion_in_progress")
        return True


class ReplaySafeDeletionSteps(Protocol):
    replay_safe: bool

    async def execute(self, job_id: UUID, owner_id: str, phase: str) -> None:
        """Return only when the step is confirmed; repeat calls must be safe."""
        ...


@dataclass(frozen=True)
class DeletionRunResult:
    status: Literal["NO_WORK", "DONE", "RETRY", "LEASE_LOST"]
    job_id: UUID | None = None
    phase: str | None = None


class AccountDeletionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        steps: ReplaySafeDeletionSteps,
        *,
        lease_seconds: int = 60,
        retry_delay_seconds: int = 30,
    ) -> None:
        if steps.replay_safe is not True:
            raise ValueError("Deletion steps must be replay-safe")
        if not 1 <= lease_seconds <= 3600 or not 0 <= retry_delay_seconds <= 86400:
            raise ValueError("Invalid deletion timing")
        self._sessions = sessions
        self._steps = steps
        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds

    async def run_once(self) -> DeletionRunResult:
        async with self._sessions.begin() as session:
            job = await AccountDeletionRepository(session).claim_next(self._lease_seconds)
            if job is None:
                return DeletionRunResult("NO_WORK")
            job_id, owner_id, phase, lease_token = job.id, job.owner_id, job.phase, job.lease_token
            if phase not in _PHASES or lease_token is None:
                raise RuntimeError("Invalid claimed deletion job")

        for current_phase in _PHASES[_PHASES.index(phase) :]:
            try:
                # Never hold a DB transaction while waiting for a step handler.
                await self._steps.execute(job_id, owner_id, current_phase)
            except Exception:
                async with self._sessions.begin() as session:
                    saved = await AccountDeletionRepository(session).retry(
                        job_id, lease_token, current_phase, "step_failed", self._retry_delay_seconds
                    )
                return DeletionRunResult("RETRY" if saved else "LEASE_LOST", job_id, current_phase)

            async with self._sessions.begin() as session:
                advanced = await AccountDeletionRepository(session).advance(
                    job_id, lease_token, current_phase
                )
            if not advanced:
                return DeletionRunResult("LEASE_LOST", job_id, current_phase)
        return DeletionRunResult("DONE", job_id, "DONE")


class _LocalDeletionSteps:
    replay_safe = True

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], accounts: Callable[[], AccountDeleter]
    ) -> None:
        self._sessions = sessions
        self._accounts = accounts

    async def execute(self, job_id: UUID, owner_id: str, phase: str) -> None:
        match phase:
            case "BLOCKING":
                # The committed job is the member fence, including after the job finishes.
                async with self._sessions() as session:
                    if await AccountDeletionRepository(session).status(owner_id) is None:
                        raise _unavailable()
            case "PURGING_CHAT":
                await delete_chatbot_account(job_id, owner_id)
            case "DELETING_AUTH":
                async with asyncio.timeout(12):
                    await self._accounts().delete_user(owner_id)
            case "DELETING_MEMBER":
                async with self._sessions() as session:
                    await MemberRepository(session).delete(owner_id)
            case _:
                raise ValueError("Unknown deletion phase")


class _LocalAuthTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        # Only confirmed deletion or an already absent user may advance the job.
        if response.status_code not in {200, 204, 404}:
            await response.aclose()
            raise httpx.RequestError("Local Auth deletion was not confirmed", request=request)
        return response


def build_local_deletion_worker() -> AccountDeletionService:
    settings = get_settings()
    key = settings.g7_local_supabase_secret_key
    if settings.env not in {"local", "test"} or not key or not key.get_secret_value():
        raise _unavailable()
    _require_local_database(settings.database_url)
    try:
        origin = httpx.URL(settings.g7_local_supabase_url or "")
    except httpx.InvalidURL:
        raise _unavailable() from None
    if (
        origin.scheme not in {"http", "https"}
        or origin.host not in {"127.0.0.1", "::1"}
        or origin.raw_path != b"/"
        or origin.userinfo
        or origin.fragment
    ):
        raise _unavailable()

    sessions = get_sessionmaker()

    def accounts() -> AccountDeleter:
        return SupabaseAdminClient(
            str(origin), key.get_secret_value(), transport=_LocalAuthTransport(trust_env=False)
        )

    return AccountDeletionService(sessions, _LocalDeletionSteps(sessions, accounts))
