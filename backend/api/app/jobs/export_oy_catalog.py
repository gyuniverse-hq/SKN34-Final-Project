"""Write a serving catalog JSON from the Olive Young raw tables.

uv run python -m app.jobs.export_oy_catalog seed/oy-catalog.json

Does not replace the live catalog. Review the file, then load it with seed_catalog.
Products without a stored price are omitted. Shades without a stored hex are not painted.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.core.observability import configure_logging
from app.schemas.catalog import CatalogBundle
from app.services.oy_catalog import load_oy_catalog

logger = logging.getLogger("export_oy_catalog")


async def export(path: Path) -> None:
    async with session_scope() as session:
        built = await load_oy_catalog(session)
    bundle = CatalogBundle(products=built.products, looks=[], stores=[])
    text = bundle.model_dump_json(indent=2, by_alias=True)
    await asyncio.to_thread(path.write_text, text, encoding="utf-8")
    logger.info(
        "olive young catalog exported",
        extra={
            "path": str(path),
            "products": len(built.products),
            "ar_products": built.ar_products,
            "ar_shades": built.ar_shades,
            "care_products": built.care_products,
            "care_products_tagged": built.care_products_tagged,
            "listed_without_color": built.listed_without_color,
            "skipped_without_price": built.skipped_without_price,
            "skipped_unknown_category": built.skipped_unknown_category,
        },
    )
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("seed/oy-catalog.json"))
    args = parser.parse_args()
    configure_logging("export_oy_catalog", get_settings().log_level)
    asyncio.run(export(args.path))


if __name__ == "__main__":
    main()
