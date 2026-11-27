"""Mock repository/HTTP contracts. Live Catalog evidence is recorded separately."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ApiError
from app.main import create_app
from app.services.product_option_service import ProductOptionService, get_product_option_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def repository():
    return SimpleNamespace(
        option_identity=AsyncMock(return_value=("o2", "Option 2", None, "https://example.test/p")),
        option_price=AsyncMock(return_value=(1, 1200, datetime(2026, 10, 28), "https://example.test/p")),
        option_image=AsyncMock(return_value=("https://example.test/chip.jpg", "color_chip")),
        option_ar_shade=AsyncMock(return_value=None),
    )


@pytest.mark.anyio
async def test_exact_option_and_recorded_price(repository):
    result = await ProductOptionService(repository).get_option("p", "o2")
    assert result.option_id == "o2"
    assert result.price_krw == 1200
    assert result.image.kind == "color_chip"
    assert result.ar_shade_id is None
    assert result.observed_at == "2026-10-28T00:00:00"
    assert result.model_dump()["priceKRW"] == 1200
    repository.option_price.assert_awaited_once_with("o2", "p")


@pytest.mark.anyio
async def test_unknowns_are_preserved(repository):
    repository.option_price.return_value = None
    repository.option_image.return_value = None
    result = await ProductOptionService(repository).get_option("p", "o2")
    assert result.price_krw is None and result.image is None
    assert result.ar_shade_id is None


@pytest.mark.anyio
async def test_wrong_or_delisted_identity_stops_lookup(repository):
    repository.option_identity.return_value = None
    with pytest.raises(ApiError):
        await ProductOptionService(repository).get_option("wrong-product", "o2")
    repository.option_price.assert_not_awaited()
    repository.option_ar_shade.assert_not_awaited()


def test_http_contract_no_store(repository):
    app = create_app()
    app.dependency_overrides[get_product_option_service] = lambda: ProductOptionService(repository)
    with TestClient(app) as client:
        result = client.get("/api/products/p/options/o2")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["priceKRW"] == 1200
    assert result.json()["optionId"] == "o2"
