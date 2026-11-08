"""Read-only Catalog API ↔ Neo4j legacy projection audit.

Run from backend/chatbot:
    uv run python -m app.jobs.audit_graph

Exit codes: 0 = parity PASS, 2 = mismatch, 3 = audit unavailable.
This job never runs graph sync, database migrations or writes.
"""

import asyncio
import json
import logging

from app.core.graph import close_driver
from app.core.observability import configure_logging
from app.services.graph_audit_service import create_graph_audit_service

logger = logging.getLogger("audit_graph")


async def run() -> int:
    try:
        report = await create_graph_audit_service().audit()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "PASS" else 2
    except Exception:
        logger.exception("graph audit unavailable")
        return 3
    finally:
        await close_driver()


def main() -> None:
    configure_logging("audit_graph", "INFO")
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
