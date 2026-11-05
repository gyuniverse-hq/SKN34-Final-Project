"""Reject malformed upstream JSON prices instead of manufacturing catalog facts."""

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.errors import UpstreamError
from tests.test_beauty_consultation import product


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("value", [True, False, "15000", "0", 15000.0, 15000.5, None])
@pytest.mark.parametrize("operation", ["search", "detail"])
async def test_upstream_price_requires_json_integer(monkeypatch, value, operation):
    row = product("typed-price", 15000).model_dump(by_alias=True)
    row["priceKRW"] = value
    original = httpx.AsyncClient

    def handler(request):
        data = {"products": [row]} if request.url.path == "/api/products" else {"product": row}
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    client = CatalogClient("http://catalog.test")
    with pytest.raises(UpstreamError):
        if operation == "search":
            await client.search_products(category="lip")
        else:
            await client.get_product("typed-price")


@pytest.mark.anyio
@pytest.mark.parametrize("value", [0, 1, 15000, -1])
async def test_integer_prices_keep_existing_unknown_nonpositive_contract(monkeypatch, value):
    row = product("integer-price", value).model_dump(by_alias=True)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"product": row})),
            **kwargs,
        ),
    )
    result = await CatalogClient("http://catalog.test").get_product("integer-price")
    assert result.price_krw == value and type(result.price_krw) is int
