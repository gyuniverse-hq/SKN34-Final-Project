"""Replace the catalog in PostgreSQL with a JSON bundle.

uv run python -m app.jobs.seed_catalog seed/catalog.json
"""

import argparse
import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.core.observability import configure_logging
from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import catalog_service_for

logger = logging.getLogger("seed_catalog")


async def run(bundle: CatalogBundle) -> None:
    async with session_scope() as session:
        await catalog_service_for(session).import_catalog(bundle)
    logger.info(
        "catalog imported",
        extra={
            "products": len(bundle.products),
            "looks": len(bundle.looks),
            "stores": len(bundle.stores),
        },
    )
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("seed/catalog.json"))
    args = parser.parse_args()
    configure_logging("seed_catalog", get_settings().log_level)
    bundle = CatalogBundle.model_validate_json(args.path.read_text(encoding="utf-8"))
    asyncio.run(run(bundle))


if __name__ == "__main__":
    main()
