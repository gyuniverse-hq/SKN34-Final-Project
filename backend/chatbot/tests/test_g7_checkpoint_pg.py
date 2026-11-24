import asyncio
import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import make_url

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
    pytest.mark.anyio,
]


@pytest.fixture
def anyio_backend():
    if os.name == "nt":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


class SafeState(TypedDict):
    result_ref: str
    execution_status: str


async def test_explicit_setup_and_safe_checkpoint_roundtrip():
    url = make_url(URL)
    if url.database != "vishue_chat_test":
        raise RuntimeError("G7 integration tests require the disposable vishue_chat_test database")
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    thread = str(uuid4())
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        await saver.setup()
        graph = StateGraph(SafeState)
        graph.add_node("finish", lambda state: {"execution_status": "done"})
        graph.add_edge(START, "finish")
        graph.add_edge("finish", END)
        compiled = graph.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": thread}}
        await compiled.ainvoke({"result_ref": "safe-reference", "execution_status": "new"}, config)
        saved = await saver.aget_tuple(config)
        assert saved.checkpoint["channel_values"]["result_ref"] == "safe-reference"
        assert saved.checkpoint["channel_values"]["execution_status"] == "done"
        assert "ChatResponse" not in str(saved.checkpoint)
        assert "sessionToken" not in str(saved.checkpoint)
        await saver.adelete_thread(thread)
        assert await saver.aget_tuple(config) is None
