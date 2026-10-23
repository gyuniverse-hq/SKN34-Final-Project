import anyio

from app.schemas.catalog import CatalogLook, CatalogProduct
from app.services.graph_sync_service import GraphSyncService

PRODUCT = CatalogProduct.model_validate(
    {
        "id": "lip-1",
        "brand": "Rom&nd",
        "name": "Juicy Tint",
        "nameKo": "쥬시 틴트",
        "category": "lip",
        "makeupZone": "lip",
        "texture": "glossy",
        "priceKRW": 13000,
        "volume": "5.5g",
        "description": "Glassy finish",
        "keyIngredients": ["Shea Butter"],
        "tags": ["Bestseller"],
        "imageUrl": "https://example.com/x.png",
        "searchKeyword": "romand juicy",
        "shades": [{"id": "01", "name": "Jujube", "hex": "#b5323c"}],
    }
)
LOOK = CatalogLook.model_validate(
    {
        "id": "look-1",
        "title": "Stage",
        "tags": ["kpop"],
        "items": [{"productId": "lip-1", "step": "lips"}],
        "makeup": {"lip": None, "blush": None, "eyeshadow": None},
    }
)


class FakeSource:
    async def fetch_products(self):
        return [PRODUCT]

    async def fetch_looks(self):
        return [LOOK]


class FakeGraph:
    def __init__(self) -> None:
        self.schema = False
        self.products: list = []
        self.looks: list = []

    async def ensure_schema(self):
        self.schema = True

    async def replace_catalog(self, products, looks):
        self.products, self.looks = products, looks


def test_sync_copies_catalog_into_graph_rows():
    graph = FakeGraph()
    counts = anyio.run(GraphSyncService(FakeSource(), graph).sync)

    assert counts == {"products": 1, "looks": 1}
    assert graph.schema
    row = graph.products[0]
    assert row["priceKRW"] == 13000
    assert row["ingredients"] == ["Shea Butter"]
    assert "쥬시 틴트" in row["searchText"] and "shea butter" in row["searchText"]
    assert row["searchText"] == row["searchText"].lower()
    assert graph.looks == [
        {
            "id": "look-1",
            "title": "Stage",
            "tags": ["kpop"],
            "items": [{"productId": "lip-1", "shadeId": None, "step": "lips"}],
        }
    ]
