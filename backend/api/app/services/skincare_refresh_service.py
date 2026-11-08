"""Background refresh of the shared skincare projection."""

import asyncio
import logging
from pathlib import Path

from app.core.config import get_settings
from app.repositories.skincare_refresh_repository import read_preview, refresh
from app.services.skincare_service import review_preview

logger = logging.getLogger(__name__)
MANIFEST = Path(__file__).resolve().parents[2] / "skincare_manifest.json"


async def preview_reviews(manifest=MANIFEST):
    return review_preview(await read_preview(manifest.read_bytes()))


async def publish_reviews(manifest=MANIFEST, **changes):
    result = await refresh(manifest.read_bytes(), **changes)
    if result == "busy":
        raise RuntimeError("Another skincare publication is running; retry")
    return result


async def run_refresh_loop() -> None:
    interval = max(5, get_settings().skincare_refresh_interval_seconds)
    while True:
        try:
            result = await refresh(MANIFEST.read_bytes())
            if result not in ("unchanged", "busy"):
                logger.info("Skincare refresh: %s", result)
        except Exception:
            logger.exception("Skincare refresh failed; existing snapshot was retained")
        await asyncio.sleep(interval)
