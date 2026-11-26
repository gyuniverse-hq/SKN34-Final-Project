"""TTL-bound Redis snapshots. Guest ownership also requires a server-issued bearer capability."""

import hmac
import json
import os
import time
from hashlib import sha256
from itertools import batched
from uuid import UUID

from pydantic import ValidationError
from redis.exceptions import RedisError, WatchError

from app.core.errors import ApiError
from app.core.ratelimit import get_redis
from app.schemas.chat import ArAdjustmentSnapshot, ChatSessionRef, ChatSessionState

_SESSION_PREFIX = "vishue:chat:session:"


def _session_scope(raw: str, session_id: UUID) -> tuple[str, UUID | None, bool]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("owner"), str):
        raise ValueError("Invalid session owner")
    stored_id = data.get("sessionId", data.get("session_id"))
    if not isinstance(stored_id, str) or UUID(stored_id) != session_id:
        raise ValueError("Invalid session key")
    room = data.get("conversationId", data.get("conversation_id"))
    persistent = (
        data.get("memoryEpoch", data.get("memory_epoch")) is not None
        or data.get("memoryGeneration", data.get("memory_generation")) is not None
    )
    return data["owner"], UUID(room) if room is not None else None, persistent


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
        return f"{_SESSION_PREFIX}{session_id}"

    @staticmethod
    def request_key(owner: str, request_id: UUID) -> str:
        return f"vishue:chat:request:{sha256(owner.encode()).hexdigest()}:{request_id}"

    def available(self):
        if self.configuration_error:
            raise ApiError(503, "Chat session configuration invalid", self.configuration_error)
        if self.client is None:
            raise ApiError(503, "Chat session storage unavailable", "chat_session_unavailable")

    def _adjustment_key(self, owner: str, session: UUID, command: UUID) -> str:
        # A late ACK can only write its own immutable result, never replace a newer turn.
        return f"{self.key(session)}:ar:{sha256(owner.encode()).hexdigest()}:{command}"

    async def save_adjustment(
        self,
        owner: str,
        session: UUID,
        command: UUID,
        snapshot: ArAdjustmentSnapshot,
        received_at: int,
    ) -> None:
        self.available()
        ttl = received_at + self.ttl_seconds - int(time.time())
        if ttl <= 0:
            return
        try:
            await self.client.set(
                self._adjustment_key(owner, session, command),
                snapshot.model_dump_json(),
                ex=ttl,
                nx=True,
            )
        except (RedisError, OSError) as exc:
            raise ApiError(
                503, "AR session storage unavailable", "chat_session_unavailable"
            ) from exc

    async def load_adjustment(
        self, owner: str, session: UUID, command: UUID
    ) -> ArAdjustmentSnapshot | None:
        self.available()
        try:
            raw = await self.client.get(self._adjustment_key(owner, session, command))
            return ArAdjustmentSnapshot.model_validate_json(raw) if raw else None
        except (RedisError, OSError, ValueError) as exc:
            raise ApiError(
                503, "AR session storage unavailable", "chat_session_unavailable"
            ) from exc

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

    async def delete_owner(self, owner_id: str) -> None:
        """Remove a blocked owner's legacy session, request and rate-limit keys."""
        self.available()
        owner = f"user:{owner_id}"
        request_prefix = f"vishue:chat:request:{sha256(owner.encode()).hexdigest()}:"
        rate_prefix = f"vishue:chat:rl:{owner}:"
        try:
            async for key in self.client.scan_iter(match="vishue:chat:session:*", count=200):
                # WATCH prevents deleting a different owner's replacement of the same key.
                for attempt in range(3):
                    try:
                        async with self.client.pipeline(transaction=True) as pipe:
                            await pipe.watch(key)
                            raw = await pipe.get(key)
                            if raw is None:
                                break
                            data = json.loads(raw)
                            if not isinstance(data, dict) or not isinstance(data.get("owner"), str):
                                raise ValueError("Invalid session owner")
                            if data["owner"] != owner:
                                break
                            session_id = UUID(key.removeprefix("vishue:chat:session:"))
                            stored_id = data.get("session_id", data.get("sessionId"))
                            if not isinstance(stored_id, str) or UUID(stored_id) != session_id:
                                raise ValueError("Invalid session key")
                            pipe.multi()
                            pipe.delete(key)
                            await pipe.execute()
                            break
                    except WatchError:
                        if attempt == 2:
                            raise

            async for key in self.client.scan_iter(match=f"{request_prefix}*", count=200):
                # The prefix contains only a digest, never an unescaped owner-supplied glob.
                if not key.startswith(request_prefix):
                    raise ValueError("Invalid request key")
                UUID(key.removeprefix(request_prefix))
                await self.client.delete(key)

            async for key in self.client.scan_iter(match="vishue:chat:rl:user:*", count=200):
                suffix = key.removeprefix(rate_prefix)
                if key.startswith(rate_prefix) and suffix.isascii() and suffix.isdigit():
                    await self.client.delete(key)
        except (RedisError, OSError, ValueError, TypeError, UnicodeError) as exc:
            raise ApiError(
                503, "Chat session storage unavailable", "chat_session_unavailable"
            ) from exc

    async def delete_room(
        self, owner_id: str, conversation_id: UUID, request_ids: list[UUID]
    ) -> None:
        self.available()
        owner = f"user:{owner_id}"
        request_keys = (self.request_key(owner, request_id) for request_id in request_ids)
        linked: dict[UUID, list[str]] = {}
        verified: set[UUID] = set()
        unconfirmed = False
        try:
            for keys in batched(request_keys, 100):
                pointers = await self.client.mget(keys)
                for key, pointer in zip(keys, pointers, strict=True):
                    if pointer is not None:
                        linked.setdefault(UUID(pointer), []).append(key)

            # A request key may be evicted while its session snapshot is still present.
            async for key in self.client.scan_iter(match=f"{_SESSION_PREFIX}*", count=200):
                session_id = UUID(key.removeprefix(_SESSION_PREFIX))
                raw = await self.client.get(key)
                if raw is None:
                    continue
                stored_owner, room, persistent = _session_scope(raw, session_id)
                if stored_owner != owner:
                    continue
                if room == conversation_id:
                    verified.add(session_id)
                elif room is None and persistent:
                    unconfirmed = True

            for session_id in linked.keys() | verified:
                key = self.key(session_id)
                keys = linked.get(session_id, [])
                async with self.client.pipeline(transaction=True) as pipe:
                    await pipe.watch(key, *keys)
                    raw = await pipe.get(key)
                    pointers = await pipe.mget(keys) if keys else []
                    refs = [
                        request_key
                        for request_key, pointer in zip(keys, pointers, strict=True)
                        if pointer is not None and UUID(pointer) == session_id
                    ]
                    if raw is None:
                        if session_id not in verified:
                            unconfirmed |= bool(refs)
                            continue
                    else:
                        stored_owner, room, persistent = _session_scope(raw, session_id)
                        if stored_owner != owner or room != conversation_id:
                            if stored_owner == owner and room is None and persistent:
                                unconfirmed = True
                            continue
                    pipe.multi()
                    pipe.delete(key, *refs)
                    acknowledgements = await pipe.execute()
                    if len(acknowledgements) != 1 or type(acknowledgements[0]) is not int:
                        raise ApiError(
                            503, "Room session cleanup is unconfirmed", "room_sessions_unconfirmed"
                        )
        except (RedisError, OSError, ValueError, TypeError, UnicodeError) as exc:
            raise ApiError(
                503, "Chat session storage unavailable", "chat_session_unavailable"
            ) from exc
        if unconfirmed:
            raise ApiError(503, "Room session cleanup is unconfirmed", "room_sessions_unconfirmed")

    async def load(
        self, owner: str, ref: ChatSessionRef, *, conversation_id: UUID | None = None
    ) -> ChatSessionState:
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
            # Older persistent snapshots have a memory fence but no room binding.
            unbound_persistent = state.conversation_id is None and (
                state.memory_epoch is not None or state.memory_generation is not None
            )
            if state.conversation_id != conversation_id or unbound_persistent:
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
                        or current.conversation_id != state.conversation_id
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
