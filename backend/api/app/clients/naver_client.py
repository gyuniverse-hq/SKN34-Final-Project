import asyncio
import html
import logging
import re
import time
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.external import ShoppingOffer

logger = logging.getLogger(__name__)

SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"
IMAGE_URL = "https://openapi.naver.com/v1/search/image.json"
# Some applications get SE05 (404) for shop.json. Back off instead of retrying every request.
SHOP_UNAVAILABLE_BACKOFF_SECONDS = 60 * 60
RETRY_AFTER_429_SECONDS = 0.7

_CATALOG_IMAGE = re.compile(
    r"^https?://(?:shopping\.phinf\.naver\.net|shopping-phinf\.pstatic\.net)(/.+)$"
)
_STORE_IMAGE = re.compile(r"^https?://(?:shop1\.phinf\.naver\.net|shop-phinf\.pstatic\.net)(/.+)$")
_TAG = re.compile(r"<[^>]+>")


def to_https_shopping_image(url: str) -> str | None:
    """Naver Shopping product images only; *.phinf.naver.net has no HTTPS, pstatic does."""
    if m := _CATALOG_IMAGE.match(url):
        return f"https://shopping-phinf.pstatic.net{m.group(1)}"
    if m := _STORE_IMAGE.match(url):
        return f"https://shop-phinf.pstatic.net{m.group(1)}"
    return None


def clean_text(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


def _price(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class NaverClient:
    """Naver Search API (shopping and image search). The only place the Naver keys are used."""

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        timeout: float = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._headers = {
            "X-Naver-Client-Id": client_id or "",
            "X-Naver-Client-Secret": client_secret or "",
        }
        self._configured = bool(client_id and client_secret)
        self._timeout = timeout
        self._transport = transport
        self._shop_unavailable_until = 0.0

    @property
    def configured(self) -> bool:
        return self._configured

    async def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                res = await c.get(url, params=params, headers=self._headers)
                if res.status_code == 429:
                    await asyncio.sleep(RETRY_AFTER_429_SECONDS)
                    res = await c.get(url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise UpstreamError("Naver request failed") from exc
        return res

    async def search_offers(self, query: str, display: int = 5) -> list[ShoppingOffer]:
        """Online sellers for a product. Empty while shop.json is unavailable for this key."""
        if not self._configured or time.monotonic() < self._shop_unavailable_until:
            return []
        res = await self._get(SHOP_URL, {"query": query, "display": display, "sort": "sim"})
        if res.status_code == 404:
            self._shop_unavailable_until = time.monotonic() + SHOP_UNAVAILABLE_BACKOFF_SECONDS
            logger.warning("naver shop.json unavailable for this application (SE05)")
            return []
        if res.status_code != 200:
            raise UpstreamError(f"Naver shopping search failed ({res.status_code})")
        offers = []
        for item in res.json().get("items", []):
            price = _price(item.get("lprice"))
            if not item.get("link") or price <= 0:
                continue
            image = item.get("image") or ""
            offers.append(
                ShoppingOffer(
                    title=clean_text(item.get("title") or ""),
                    mall_name=item.get("mallName") or "",
                    price_krw=price,
                    image_url=to_https_shopping_image(image) or image,
                    link=item["link"],
                )
            )
        return offers

    async def search_product_images(self, query: str) -> list[str]:
        """HTTPS Naver Shopping product photos from image search (never blog or social images)."""
        if not self._configured:
            return []
        res = await self._get(IMAGE_URL, {"query": query, "display": 30, "sort": "sim"})
        if res.status_code != 200:
            raise UpstreamError(f"Naver image search failed ({res.status_code})")
        urls = (to_https_shopping_image(i.get("link") or "") for i in res.json().get("items", []))
        return [u for u in urls if u]


@lru_cache
def get_naver_client() -> NaverClient:
    s = get_settings()
    return NaverClient(s.naver_client_id, s.naver_client_secret)
