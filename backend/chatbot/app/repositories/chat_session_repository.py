"""TTL-bound Redis snapshots. Guest ownership also requires a server-issued bearer capability."""

import hmac
import os
import time
from hashlib import sha256
from uuid import UUID

from pydantic import ValidationError
from redis.exceptions import RedisError, WatchError

from app.core.errors import ApiError
from app.core.ratelimit import get_redis
from app.schemas.chat import ChatSessionRef, ChatSessionState


class ChatSessionRepository:
    def __init__(self, client, ttl_seconds: int = 600):
        if not 1 <= ttl_seconds <= 600:
            raise ApiError(
                503, "Session TTL must be between 1 and 600", "chat_session_config_invalid"
            )
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.configuration_error: str | None = None

    @staticmethod
    def key(session_id: UUID) -> str:
        return f"vishue:chat:session:{session_id}"

    @staticmethod
    def request_key(owner: str, request_id: UUID) -> str:
        return f"vishue:chat:request:{sha256(owner.encode()).hexdigest()}:{request_id}"

    def available(self):
        if self.configuration_error:
            raise ApiError(503, "Chat session configuration invalid", self.configuration_error)
        if self.client is None:
            raise ApiError(503, "Chat session storage unavailable", "chat_session_unavailable")

    async def check_new_request(self, owner: str, request_id: UUID):
        self.available()
        try:
            if await self.client.get(self.request_key(owner, request_id)) is not None:
                raise ApiError(
                    409, "Committed request requires its session reference", "chat_request_conflict"
                )
        except (RedisError, OSError) as exc:
            raise ApiError(
                503, "Chat session storage unavailable", "chat_session_unavailable"
            ) from exc

    async def load(self, owner: str, ref: ChatSessionRef) -> ChatSessionState:
        self.available()
        try:
            raw = await self.client.get(self.key(ref.session_id))
            if raw is None:
                raise ApiError(410, "Chat session expired", "chat_session_expired")
            state = ChatSessionState.model_validate_json(raw)
            if state.session_id != ref.session_id:
                raise ValueError("Session key mismatch")
            if state.owner != owner or not hmac.compare_digest(
                state.token_hash, sha256(ref.session_token.encode()).hexdigest()
            ):
                raise ApiError(403, "Chat session access denied", "chat_session_forbidden")
            if state.expires_at <= int(time.time()):
                raise ApiError(410, "Chat session expired", "chat_session_expired")
            return state
        except (RedisError, OSError, ValueError, ValidationError) as exc:
            raise ApiError(
                503, "Chat session storage unavailable", "chat_session_unavailable"
            ) from exc

    async def commit(self, state: ChatSessionState, expected_version: int | None) -> None:
        self.available()
        key = self.key(state.session_id)
        request_key = self.request_key(state.owner, state.last_request_id)
        try:
            async with self.client.pipeline(transaction=True) as pipe:
                await pipe.watch(key, request_key)
                raw = await pipe.get(key)
                used = await pipe.get(request_key)
                if used is not None:
                    # Never reveal another session's capability via an idempotency key.
                    raise ApiError(409, "Request already committed", "chat_request_conflict")
                current = ChatSessionState.model_validate_json(raw) if raw else None
                if expected_version is not None and current is None:
                    raise ApiError(410, "Chat session expired", "chat_session_expired")
                if (expected_version is None and current is not None) or (
                    expected_version is not None
                    and (
                        current is None
                        or current.state_version != expected_version
                        or current.owner != state.owner
                        or current.token_hash != state.token_hash
                    )
                ):
                    raise ApiError(409, "Chat session changed", "chat_session_conflict")
                ttl = state.expires_at - int(time.time())
                if ttl <= 0:
                    raise ApiError(410, "Chat session expired", "chat_session_expired")
                pipe.multi()
                pipe.set(key, state.model_dump_json(), ex=ttl)
                pipe.set(request_key, str(state.session_id), ex=ttl)
                acknowledgements = await pipe.execute()
                if acknowledgements != [True, True]:
                    raise ApiError(
                        503, "Chat session write unconfirmed", "chat_session_unavailable"
                    )
        except WatchError as exc:
            raise ApiError(409, "Chat session changed", "chat_session_conflict") from exc
        except (RedisError, OSError, ValueError, ValidationError) as exc:
            raise ApiError(
                503, "Chat session storage unavailable", "chat_session_unavailable"
            ) from exc


def get_chat_sessions() -> ChatSessionRepository:
    try:
        ttl = int(os.environ.get("CHAT_SESSION_TTL_SECONDS", "600"))
        return ChatSessionRepository(get_redis(), ttl)
    except ApiError:
        repository = ChatSessionRepository(None)
        repository.configuration_error = "chat_session_config_invalid"
        return repository
    except (ValueError, RedisError):
        # Keep independent/general routes available; session operations still fail closed.
        repository = ChatSessionRepository(None)
        repository.configuration_error = "chat_session_config_invalid"
        return repository
