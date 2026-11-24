import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.conversation import (
    ChatConversation,
    ChatMemory,
    ChatMessage,
    ChatOwnerStatus,
    ChatTurn,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
    pytest.mark.anyio,
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def sessions():
    if make_url(URL).database != "vishue_chat_test":
        raise RuntimeError("G7 integration tests require the disposable vishue_chat_test database")
    engine = create_async_engine(URL)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_owner_isolation_memory_revocation_and_deleting_owner(sessions):
    alice, bob = str(uuid4()), str(uuid4())
    room, thread, message_id, memory_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with sessions.begin() as session:
        repo = ConversationRepository(session)
        assert await repo.create(alice, room, thread, {"type": "general"})
        assert await repo.ensure_active_owner(bob)
        message = ChatMessage(
            id=message_id,
            conversation_id=room,
            sequence=1,
            role="user",
            text="coral",
            display_payload={},
        )
        assert await repo.add_message(alice, room, message)
        assert not await repo.add_message(
            bob,
            room,
            ChatMessage(
                id=uuid4(),
                conversation_id=room,
                sequence=2,
                role="user",
                text="x",
                display_payload={},
            ),
        )
        memory = MemoryRepository(session)
        assert await memory.create(
            alice,
            memory_id,
            "preference",
            "lip",
            {"color": "coral"},
            "personalization",
            datetime.now(UTC),
            message_id,
        )
        assert (
            await memory.create(
                bob,
                uuid4(),
                "preference",
                "lip",
                {},
                "personalization",
                datetime.now(UTC),
                message_id,
            )
            is None
        )
        assert await repo.get(bob, room) is None
        assert await repo.messages(bob, room) == []
        assert await memory.get(bob, memory_id) is None
        assert await memory.update(bob, memory_id, 1, {"color": "red"}) is None
        assert not await memory.revoke(bob, memory_id)
        assert await memory.update(alice, memory_id, 1, {"color": "red"}) == 2
        assert await memory.update(alice, memory_id, 1, {}) is None
        assert await memory.revoke(alice, memory_id)
        assert await memory.revoke(alice, memory_id)
        assert (await session.get(ChatOwnerStatus, alice)).revocation_epoch == 1
        await session.execute(
            update(ChatOwnerStatus)
            .where(ChatOwnerStatus.owner_id == alice)
            .values(status="DELETING")
        )
        assert not await repo.ensure_active_owner(alice)
        assert await repo.get(alice, room) is None
        assert await memory.get(alice, memory_id) is None
    async with sessions() as session:
        row = await session.get(ChatMemory, memory_id)
        assert row.value_json is None and row.revoked_at is not None
        assert (
            await session.scalar(
                select(ChatMemory.value_json.is_(None)).where(ChatMemory.id == memory_id)
            )
            is True
        )


async def test_compare_and_swap_allows_one_concurrent_commit(sessions):
    owner, room = str(uuid4()), uuid4()
    async with sessions.begin() as session:
        await ConversationRepository(session).create(owner, room, uuid4(), {"type": "general"})

    async def update_one(value):
        async with sessions.begin() as session:
            return await ConversationRepository(session).update_context(
                owner, room, 0, {"schemaVersion": 1, "currentGoal": {"domain": value}}
            )

    results = await asyncio.gather(update_one("product"), update_one("style"))
    assert sorted(results, key=lambda x: x is None) == [1, None]


async def test_turn_fencing_and_atomic_rollback(sessions):
    owner, room, request = str(uuid4()), uuid4(), uuid4()
    async with sessions.begin() as session:
        repo = ConversationRepository(session)
        await repo.create(owner, room, uuid4(), {"type": "general"})
        assert await repo.reserve_turn(
            owner, room, request, "a" * 64, 0, datetime.now(UTC) + timedelta(minutes=5)
        )
        assert not await repo.reserve_turn(
            owner, room, uuid4(), "b" * 64, 0, datetime.now(UTC) + timedelta(minutes=5)
        )
        await session.execute(
            update(ChatTurn)
            .where(ChatTurn.owner_id == owner, ChatTurn.request_id == request)
            .values(attempt_count=2)
        )
        assert await repo.get_turn(owner, request) is not None
        assert await repo.get_turn("other-owner", request) is None
        assert not await repo.finish_turn(
            owner,
            room,
            request,
            uuid4(),
            1,
            0,
            {},
            [
                ChatMessage(id=uuid4(), conversation_id=room, sequence=1, role="user", text="hi"),
                ChatMessage(
                    id=uuid4(), conversation_id=room, sequence=2, role="assistant", text="ok"
                ),
            ],
        )

    def message(seq, role):
        return ChatMessage(
            id=uuid4(),
            conversation_id=room,
            sequence=seq,
            role=role,
            text="hello",
            display_payload={},
        )

    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await ConversationRepository(session).finish_turn(
                owner,
                room,
                request,
                uuid4(),
                2,
                0,
                {"schemaVersion": 1},
                [message(1, "user"), message(1, "assistant")],
            )
    async with sessions() as session:
        assert (await session.get(ChatConversation, room)).conversation_version == 0
        assert (await session.get(ChatTurn, (owner, request))).status == "IN_PROGRESS"
        assert await ConversationRepository(session).messages(owner, room) == []
    async with sessions.begin() as session:
        assert await ConversationRepository(session).finish_turn(
            owner,
            room,
            request,
            uuid4(),
            2,
            0,
            {"schemaVersion": 1},
            [message(1, "user"), message(2, "assistant")],
        )
    async with sessions() as session:
        turn = await session.get(ChatTurn, (owner, request))
        assert turn.status == "COMMITTED"
        messages = await ConversationRepository(session).messages(owner, room)
        assert len(messages) == 2 and all(item.request_id == request for item in messages)
        assert turn.response_message_id == messages[1].id and turn.turn_id is not None
        assert (await session.get(ChatConversation, room)).conversation_version == 1


async def test_persistence_rejects_sensitive_context_and_deleted_rooms(sessions):
    owner, room = str(uuid4()), uuid4()
    async with sessions.begin() as session:
        repo = ConversationRepository(session)
        await repo.create(owner, room, uuid4(), {"type": "general"})
        with pytest.raises(ValueError):
            await repo.update_context(owner, room, 0, {"style": {"sessionToken": "secret"}})
        with pytest.raises(ValueError):
            await repo.add_message(
                owner,
                room,
                ChatMessage(
                    id=uuid4(),
                    conversation_id=room,
                    sequence=1,
                    role="assistant",
                    text="x",
                    display_payload={"unexpected": "not allowed"},
                ),
            )
        assert await repo.mark_deleted(owner, room)
        assert await repo.get(owner, room) is None
        assert await repo.update_context(owner, room, 0, {"schemaVersion": 1}) is None
        assert (
            await session.scalar(
                select(ChatOwnerStatus.status).where(ChatOwnerStatus.owner_id == owner)
            )
        ) == "ACTIVE"
