"""Run once as a deployment/migration step, never during API startup."""

import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

from app.core.config import get_settings


async def setup() -> None:
    url = get_settings().chat_database_url
    if not url:
        raise RuntimeError("CHAT_DATABASE_URL is required for checkpoint setup")
    dsn = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(setup(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(setup())
