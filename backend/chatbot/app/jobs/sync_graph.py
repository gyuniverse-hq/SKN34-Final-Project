"""Copy the catalog from the api service into Neo4j (run by a CronJob / one-off container).

uv run python -m app.jobs.sync_graph
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.graph import close_driver
from app.core.observability import configure_logging
from app.services.graph_sync_service import create_graph_sync_service

logger = logging.getLogger("sync_graph")


async def run() -> None:
    try:
        counts = await create_graph_sync_service().sync()
        logger.info("graph synced", extra=counts)
    finally:
        await close_driver()


def main() -> None:
    configure_logging("sync_graph", get_settings().log_level)
    asyncio.run(run())


if __name__ == "__main__":
    main()
