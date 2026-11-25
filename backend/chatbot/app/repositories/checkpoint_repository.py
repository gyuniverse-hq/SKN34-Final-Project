"""Checkpoint deletion is separate from conversation transactions and is retryable."""

from contextlib import asynccontextmanager
from functools import partial
from uuid import UUID

import anyio
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url


def _lock_thread(saver, thread_id: UUID) -> None:
    key = f"g7:checkpoint:{thread_id}"
    if not saver.conn.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired", (key,)
    ).fetchone()["acquired"]:
        raise OSError("Checkpoint thread is busy")


def _guard_active(saver, thread_id, conversation_id, owner_id, request_id):
    _lock_thread(saver, thread_id)
    active = saver.conn.execute(
        "SELECT EXISTS (SELECT 1 FROM chat_conversations c "
        "JOIN chat_owner_status o ON o.owner_id = c.owner_id "
        "JOIN chat_turns t ON t.conversation_id = c.id AND t.owner_id = c.owner_id "
        "WHERE c.id = %s AND c.thread_id = %s AND c.owner_id = %s "
        "AND c.deleted_at IS NULL AND o.status = 'ACTIVE' "
        "AND t.request_id = %s AND t.status = 'IN_PROGRESS' AND t.attempt_count = 1 "
        "AND t.lease_until > clock_timestamp()) AS active",
        (conversation_id, thread_id, owner_id, request_id),
    ).fetchone()["active"]
    if not active:
        raise OSError("Conversation is no longer active")


class _FreshCheckpointWriter(BaseCheckpointSaver):
    """Persist this run without loading the thread's unapproved latest checkpoint."""

    def __init__(self, saver):
        super().__init__(serde=saver.serde)
        self._saver = saver
        self.last_config = None

    def get_next_version(self, current, channel):
        return self._saver.get_next_version(current, channel)

    async def aget_tuple(self, config):
        return None

    async def aput(self, config, checkpoint, metadata, new_versions):
        result = await anyio.to_thread.run_sync(
            partial(self._saver.put, config, checkpoint, metadata, new_versions)
        )
        self.last_config = result
        return result

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await anyio.to_thread.run_sync(
            partial(self._saver.put_writes, config, writes, task_id, task_path)
        )

    async def completed_id(self, request_id: UUID) -> str:
        if not self.last_config:
            raise ValueError("Missing completed checkpoint")
        item = await anyio.to_thread.run_sync(partial(self._saver.get_tuple, self.last_config))
        values = item.checkpoint.get("channel_values", {}) if item else {}
        if values.get("request_id") != str(request_id) or values.get("execution_status") != "done":
            raise ValueError("Invalid completed checkpoint")
        checkpoint_id = self.last_config["configurable"].get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise ValueError("Missing checkpoint ID")
        return checkpoint_id


class CheckpointRepository:
    def __init__(self, database_url: str) -> None:
        self._dsn = (
            make_url(database_url)
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )

    @asynccontextmanager
    async def fresh_writer(self, thread_id, conversation_id, owner_id, request_id):
        manager = PostgresSaver.from_conn_string(self._dsn)
        saver = await anyio.to_thread.run_sync(manager.__enter__)
        try:
            await anyio.to_thread.run_sync(
                partial(_guard_active, saver, thread_id, conversation_id, owner_id, request_id)
            )
            yield _FreshCheckpointWriter(saver)
        finally:
            await anyio.to_thread.run_sync(partial(manager.__exit__, None, None, None))

    def _delete(self, thread_id: UUID) -> None:
        with PostgresSaver.from_conn_string(self._dsn) as saver:
            _lock_thread(saver, thread_id)
            saver.delete_thread(str(thread_id))

    async def delete_thread(self, thread_id: UUID) -> None:
        await anyio.to_thread.run_sync(partial(self._delete, thread_id))
