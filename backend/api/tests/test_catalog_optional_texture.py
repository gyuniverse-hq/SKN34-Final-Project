import asyncio

import pytest

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog
from app.services.image_service import MAX_LIST_IMAGE_LOOKUPS, ProductImageService
from tests.conftest import SAMPLE


def test_unknown_texture_is_valid_for_listed_product_but_not_try_on():
    product = SAMPLE.products[0].model_copy(update={"makeup_zone": None, "texture": None})
    validate_catalog(CatalogBundle(products=[product]))
    with pytest.raises(ValueError, match="known texture"):
        validate_catalog(
            CatalogBundle(products=[product.model_copy(update={"makeup_zone": "lip"})])
        )


class ImageSource:
    configured = True

    async def search_offers(self, query, display=5):
        raise AssertionError("A full product listing must not request one image per row")

    async def search_product_images(self, query):
        raise AssertionError("A full product listing must not request one image per row")


def test_full_catalog_listing_skips_individual_image_lookups():
    image_service = ProductImageService(ImageSource(), None)
    products = [SAMPLE.products[0]] * (MAX_LIST_IMAGE_LOOKUPS + 1)
    assert asyncio.run(image_service.with_live_images(products)) == products
