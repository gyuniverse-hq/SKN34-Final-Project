import anyio
import pytest
from fastapi.testclient import TestClient

from app.core.cache import NullCache
from app.core.errors import UpstreamError
from app.core.ratelimit import (
    MemoryRateLimiter,
    get_offer_search_rate_limiter,
    get_tutorial_rate_limiter,
)
from app.main import create_app
from app.schemas.external import Integrations, ShoppingOffer, YoutubeVideo
from app.services.catalog_service import CatalogService, get_catalog_service
from app.services.image_service import ProductImageService
from app.services.offer_service import OfferService, get_offer_service
from app.services.tutorial_service import (
    TutorialService,
    build_tutorial_query,
    get_tutorial_service,
)
from tests.conftest import SAMPLE, FakeCatalogStore

OFFER = ShoppingOffer(
    title="Juicy Tint",
    mall_name="Mall",
    price_krw=12900,
    image_url="https://img/1.jpg",
    link="https://s/1",
)
VIDEO = YoutubeVideo(
    video_id="v1",
    title="Look",
    channel_title="C",
    thumbnail_url="https://i/1.jpg",
    published_at="2026",
)


class FakeNaver:
    def __init__(self, configured=True, error=False, images=None):
        self.configured = configured
        self.error = error
        self.images = images if images is not None else ["https://shopping-phinf.pstatic.net/x.jpg"]
        self.calls = 0

    async def search_offers(self, query, display=5):
        self.calls += 1
        if self.error:
            raise UpstreamError("boom")
        return [OFFER]

    async def search_product_images(self, query):
        return self.images


class FakeYoutube:
    def __init__(self, configured=True, error=False):
        self.configured = configured
        self.error = error
        self.queries: list[str] = []

    async def search_videos(self, query, max_results=8):
        self.queries.append(query)
        if self.error:
            raise UpstreamError("boom")
        return [VIDEO]


def make_client(naver=None, youtube=None, limit=20) -> TestClient:
    app = create_app()
    store = FakeCatalogStore(SAMPLE)
    app.dependency_overrides[get_catalog_service] = lambda: CatalogService(store, NullCache(), 60)
    app.dependency_overrides[get_offer_service] = lambda: OfferService(
        store, naver or FakeNaver(), NullCache()
    )
    tutorial = TutorialService(youtube or FakeYoutube(), NullCache())
    limiter = MemoryRateLimiter(limit)
    app.dependency_overrides[get_tutorial_service] = lambda: tutorial
    app.dependency_overrides[get_tutorial_rate_limiter] = lambda: limiter
    offer_limiter = MemoryRateLimiter(limit)
    app.dependency_overrides[get_offer_search_rate_limiter] = lambda: offer_limiter
    return TestClient(app)


def test_offers_use_the_product_search_keyword():
    res = make_client().get("/api/products/lip-1/offers")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=1800, s-maxage=1800"
    assert res.json() == {
        "configured": True,
        "offers": [{"title": "Juicy Tint", "mallName": "Mall", "priceKRW": 12900,
                    "imageUrl": "https://img/1.jpg", "link": "https://s/1"}],
    }  # fmt: skip


@pytest.mark.parametrize(
    ("naver", "product", "status", "body"),
    [
        (FakeNaver(configured=False), "lip-1", 200, {"configured": False, "offers": []}),
        (FakeNaver(), "nope", 404, {"error": "Product not found", "code": "not_found"}),
        (
            FakeNaver(error=True),
            "lip-1",
            502,
            {"error": "Shopping search is temporarily unavailable", "code": "upstream_error"},
        ),
    ],
)
def test_offer_edge_cases(naver, product, status, body):
    res = make_client(naver=naver).get(f"/api/products/{product}/offers")
    assert (res.status_code, res.json()) == (status, body)


def test_offer_search_finds_sellers_for_free_text():
    naver = FakeNaver()
    res = make_client(naver=naver).get("/api/offers/search?q=%20velvet%20red%20lip%20")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=1800, s-maxage=1800"
    assert res.json()["configured"] is True
    assert res.json()["offers"][0]["link"] == "https://s/1"
    assert naver.calls == 1


@pytest.mark.parametrize(
    ("path", "naver", "limit", "status", "body"),
    [
        (
            "/api/offers/search?q=%20",
            None,
            20,
            400,
            {"error": "Missing query", "code": "missing_query"},
        ),
        (
            "/api/offers/search?q=red",
            FakeNaver(configured=False),
            20,
            200,
            {"configured": False, "offers": []},
        ),
        (
            "/api/offers/search?q=red",
            FakeNaver(error=True),
            20,
            502,
            {"error": "Shopping search is temporarily unavailable", "code": "upstream_error"},
        ),
    ],
)
def test_offer_search_edge_cases(path, naver, limit, status, body):
    res = make_client(naver=naver, limit=limit).get(path)
    assert (res.status_code, res.json()) == (status, body)


def test_offer_search_is_rate_limited():
    client = make_client(limit=1)
    assert client.get("/api/offers/search?q=red").status_code == 200
    assert client.get("/api/offers/search?q=red").status_code == 429


def test_tutorial_search_builds_query_and_caches_response():
    youtube = FakeYoutube()
    res = make_client(youtube=youtube).get("/api/youtube/search?q=Jisoo&max=99")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=3600, s-maxage=3600"
    assert res.json()["configured"] is True
    assert res.json()["videos"][0]["videoId"] == "v1"
    assert youtube.queries == ["Jisoo makeup tutorial"]


def test_tutorial_search_requires_a_query():
    res = make_client().get("/api/youtube/search?q=%20")
    assert (res.status_code, res.json()["code"]) == (400, "missing_query")


def test_tutorial_search_without_key_is_not_an_error():
    res = make_client(youtube=FakeYoutube(configured=False)).get("/api/youtube/search?q=Jisoo")
    assert (res.status_code, res.json()) == (200, {"configured": False, "videos": []})


def test_tutorial_search_is_rate_limited_and_maps_upstream_errors():
    client = make_client(limit=1)
    assert client.get("/api/youtube/search?q=a1").status_code == 200
    assert client.get("/api/youtube/search?q=a2").json()["code"] == "rate_limited"
    failing = make_client(youtube=FakeYoutube(error=True)).get("/api/youtube/search?q=a1")
    assert (failing.status_code, failing.json()["code"]) == (502, "upstream_error")


def test_tutorial_keywords_are_appended_only_when_missing():
    assert build_tutorial_query("Jisoo") == "Jisoo makeup tutorial"
    assert build_tutorial_query("jisoo makeup") == "jisoo makeup"
    assert build_tutorial_query("지수 메이크업") == "지수 메이크업"


def test_health_reports_integrations(monkeypatch):
    from app.routers import health

    monkeypatch.setattr(
        health, "get_integrations", lambda: Integrations(youtube=True, naver_shopping=False)
    )
    res = make_client().get("/api/health")
    assert res.json() == {"ok": True, "integrations": {"youtube": True, "naverShopping": False}}


def test_live_images_replace_placeholders_and_keep_originals_on_failure():
    products = SAMPLE.products[:2]

    service = ProductImageService(FakeNaver(), NullCache())
    enriched = anyio.run(service.with_live_images, products)
    assert [p.image_url for p in enriched] == ["https://img/1.jpg"] * 2

    class Broken(FakeNaver):
        async def search_product_images(self, query):
            raise UpstreamError("boom")

    service = ProductImageService(Broken(error=True), NullCache())
    assert anyio.run(service.with_live_images, products) == products

    unconfigured = ProductImageService(FakeNaver(configured=False), NullCache())
    assert anyio.run(unconfigured.with_live_images, products) == products


def test_image_search_is_used_when_shopping_has_no_https_image():
    class NoOffers(FakeNaver):
        async def search_offers(self, query, display=5):
            return []

    service = ProductImageService(NoOffers(), NullCache())
    assert anyio.run(service.find_image, "tint") == "https://shopping-phinf.pstatic.net/x.jpg"
