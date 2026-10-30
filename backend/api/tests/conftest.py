import pytest
from fastapi.testclient import TestClient

from app.core.cache import NullCache
from app.main import create_app
from app.schemas.catalog import CatalogBundle, CelebLook, Product, Store
from app.schemas.member import MemberRecord
from app.services.catalog_service import CatalogService, get_catalog_service


def make_product(pid: str, category: str, shades: list[tuple[str, str, str]], **extra) -> Product:
    return Product.model_validate(
        {
            "id": pid,
            "brand": "Brand",
            "name": f"Product {pid}",
            "nameKo": f"제품 {pid}",
            "category": category,
            "makeupZone": "lip" if category == "lip" else None,
            "texture": "matte",
            "priceKRW": 18000,
            "volume": "30ml",
            "shades": [{"id": i, "name": n, "hex": h} for i, n, h in shades],
            "description": "desc",
            "keyIngredients": ["niacinamide"],
            "tags": ["bestseller"],
            "imageUrl": "https://example.com/p.png",
            "searchKeyword": f"brand {pid}",
            **extra,
        }
    )


SAMPLE = CatalogBundle(
    products=[
        make_product("lip-1", "lip", [("r1", "Rose", "#c0485a")]),
        make_product("base-1", "base", [("21", "Light", "#f1d3b9"), ("23", "Medium", "#d9b08c")]),
        make_product("base-2", "base", [("13", "Fair", "#f6e2d0"), ("40", "Deep", "#8a5a3c")]),
    ],
    looks=[
        CelebLook.model_validate(
            {
                "id": "look-1",
                "title": "Stage",
                "inspiration": "Inspired by stage looks",
                "description": "d",
                "thumbnailUrl": "https://example.com/l.png",
                "tutorialQuery": "stage makeup",
                "items": [{"productId": "lip-1", "shadeId": "r1", "step": "lips"}],
                "makeup": {"lip": {"hex": "#c0485a", "intensity": 0.7, "texture": "matte"},
                           "blush": None, "eyeshadow": None},
                "tags": [],
            }
        )
    ],
    stores=[
        Store.model_validate({"id": "s1", "name": "Myeongdong", "address": "a", "district": "Jung",
                              "lat": 37.56, "lng": 126.98, "hours": "10-22",
                              "pickupAvailable": True}),
        Store.model_validate({"id": "s2", "name": "Hongdae", "address": "b", "district": "Mapo",
                              "lat": 37.55, "lng": 126.92, "hours": "10-22",
                              "pickupAvailable": False}),
    ],
)  # fmt: skip


class FakeCatalogStore:
    """In-memory stand-in for CatalogRepository with the same search semantics."""

    def __init__(self, bundle: CatalogBundle) -> None:
        self.bundle = bundle

    async def search_products(self, terms, category=None, ids=None, tags=None):
        out = self.bundle.products
        if ids is not None:
            out = [p for p in out if p.id in ids]
        if category:
            out = [p for p in out if p.category == category]
        if tags is not None:
            out = [p for p in out if set(p.tags) & set(tags)]
        for t in terms:
            out = [p for p in out if t in f"{p.brand} {p.name} {' '.join(p.tags)}".lower()]
        return out

    async def get_product(self, product_id):
        return next((p for p in self.bundle.products if p.id == product_id), None)

    async def list_looks(self):
        return self.bundle.looks

    async def get_look(self, look_id):
        return next((lk for lk in self.bundle.looks if lk.id == look_id), None)

    async def list_stores(self):
        return self.bundle.stores

    async def replace_catalog(self, bundle):
        self.bundle = bundle


class FakeMembers:
    """In-memory stand-in for MemberRepository."""

    def __init__(self) -> None:
        self.rows: dict[str, MemberRecord] = {}

    async def get(self, member_id):
        return self.rows.get(member_id)

    async def save_terms(self, member_id, version, agreed_at):
        row = MemberRecord(id=member_id, terms_version=version, terms_agreed_at=agreed_at)
        self.rows[member_id] = row
        return row

    async def delete(self, member_id):
        self.rows.pop(member_id, None)


class FakeAccounts:
    def __init__(self, error: Exception | None = None) -> None:
        self.deleted: list[str] = []
        self._error = error

    async def delete_user(self, user_id):
        if self._error:
            raise self._error
        self.deleted.append(user_id)


@pytest.fixture
def catalog_service() -> CatalogService:
    return CatalogService(FakeCatalogStore(SAMPLE), NullCache(), 60)


@pytest.fixture
def client(catalog_service: CatalogService) -> TestClient:
    return client_for(catalog_service)


def client_for(catalog_service: CatalogService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    return TestClient(app)
