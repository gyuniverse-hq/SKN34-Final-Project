import anyio

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import CatalogService
from tests.conftest import SAMPLE, FakeCatalogStore


class DictCache:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get_json(self, key):
        return self.data.get(key)

    async def set_json(self, key, value, ttl_seconds):
        self.data[key] = value

    async def delete_prefix(self, prefix):
        for key in [k for k in self.data if k.startswith(prefix)]:
            del self.data[key]


def test_import_invalidates_cached_listings():
    cache = DictCache()
    store = FakeCatalogStore(CatalogBundle())
    service = CatalogService(store, cache, 60)

    async def scenario():
        assert await service.list_products() == []
        assert await service.list_looks() == []
        await service.import_catalog(SAMPLE)
        return await service.list_products(), await service.list_looks()

    products, looks = anyio.run(scenario)
    assert [p.id for p in products] == ["lip-1", "base-1", "base-2"]
    assert [lk.id for lk in looks] == ["look-1"]
