"""Run the local account deletion worker independently of the API server."""

import argparse
import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.db import dispose_engine
from app.core.errors import ApiError
from app.services.account_deletion_service import build_local_deletion_worker

logger = logging.getLogger(__name__)


async def process(*, once: bool) -> None:
    try:
        worker = build_local_deletion_worker()
        while True:
            try:
                result = await worker.run_once()
            except (SQLAlchemyError, OSError):
                if once:
                    raise
                logger.warning("Deletion queue database unavailable")
            else:
                if result.status != "NO_WORK" or once:
                    logger.info(
                        "Deletion worker %s job=%s phase=%s",
                        result.status,
                        result.job_id,
                        result.phase,
                    )
                if once:
                    return
                if result.status == "DONE":
                    continue
            await asyncio.sleep(2)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one available job and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(process(once=args.once))
    except ApiError as exc:
        raise SystemExit(exc.message) from None


if __name__ == "__main__":
    main()
