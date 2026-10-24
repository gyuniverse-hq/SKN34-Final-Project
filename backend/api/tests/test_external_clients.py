import anyio
import httpx
import pytest

from app.clients.naver_client import NaverClient, clean_text, to_https_shopping_image
from app.clients.youtube_client import YoutubeClient
from app.core.errors import UpstreamError


def transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return routes[request.url.path]

    mock = httpx.MockTransport(handler)
    mock.calls = calls  # type: ignore[attr-defined]
    return mock


def test_shopping_images_are_rewritten_to_https_and_other_hosts_rejected():
    assert (
        to_https_shopping_image("http://shopping.phinf.naver.net/main_1/2.jpg")
        == "https://shopping-phinf.pstatic.net/main_1/2.jpg"
    )
    assert (
        to_https_shopping_image("https://shopping-phinf.pstatic.net/main_1/2.jpg")
        == "https://shopping-phinf.pstatic.net/main_1/2.jpg"
    )
    assert (
        to_https_shopping_image("http://shop1.phinf.naver.net/20240101_1/a.jpg")
        == "https://shop-phinf.pstatic.net/20240101_1/a.jpg"
    )
    assert to_https_shopping_image("https://i.pinimg.com/736x/a.jpg") is None


def test_titles_lose_tags_and_entities():
    assert clean_text("<b>Tom</b> &amp; Jerry&#39;s &quot;look&quot;") == 'Tom & Jerry\'s "look"'


def test_unconfigured_naver_makes_no_requests():
    mock = transport({})
    client = NaverClient(None, None, transport=mock)
    assert not client.configured
    assert anyio.run(client.search_offers, "tint") == []
    assert mock.calls == []


def test_offers_are_parsed_and_invalid_items_dropped():
    items = [
        {"title": "<b>Juicy</b> Tint", "link": "https://s/1", "lprice": "12900",
         "mallName": "Mall", "image": "http://shopping.phinf.naver.net/a.jpg"},
        {"title": "no link", "lprice": "1000"},
        {"title": "free", "link": "https://s/2", "lprice": "0"},
    ]  # fmt: skip
    mock = transport({"/v1/search/shop.json": httpx.Response(200, json={"items": items})})
    client = NaverClient("id", "secret", transport=mock)
    [offer] = anyio.run(client.search_offers, "tint")
    assert (offer.title, offer.price_krw, offer.mall_name) == ("Juicy Tint", 12900, "Mall")
    assert offer.image_url == "https://shopping-phinf.pstatic.net/a.jpg"
    assert mock.calls[0].headers["X-Naver-Client-Id"] == "id"


def test_shop_404_backs_off_instead_of_retrying():
    mock = transport({"/v1/search/shop.json": httpx.Response(404)})
    client = NaverClient("id", "secret", transport=mock)
    assert anyio.run(client.search_offers, "tint") == []
    assert anyio.run(client.search_offers, "tint") == []
    assert len(mock.calls) == 1


def test_naver_errors_raise_upstream_error():
    mock = transport({"/v1/search/image.json": httpx.Response(500)})
    with pytest.raises(UpstreamError):
        anyio.run(NaverClient("id", "secret", transport=mock).search_product_images, "tint")


def test_image_search_keeps_only_naver_shopping_hosts():
    items = [{"link": "https://blog.example/a.jpg"}, {"link": "http://shop1.phinf.naver.net/b.jpg"}]
    mock = transport({"/v1/search/image.json": httpx.Response(200, json={"items": items})})
    urls = anyio.run(NaverClient("id", "secret", transport=mock).search_product_images, "tint")
    assert urls == ["https://shop-phinf.pstatic.net/b.jpg"]


def test_youtube_results_are_parsed_with_thumbnail_fallback():
    items = [
        {"id": {"videoId": "v1"}, "snippet": {"title": "Jisoo &amp; makeup", "channelTitle": "C",
         "publishedAt": "2026-01-01", "thumbnails": {"medium": {"url": "https://i/m.jpg"}}}},
        {"id": {}, "snippet": {"title": "channel result"}},
    ]  # fmt: skip
    mock = transport({"/youtube/v3/search": httpx.Response(200, json={"items": items})})
    [video] = anyio.run(YoutubeClient("key", transport=mock).search_videos, "jisoo")
    assert (video.video_id, video.title, video.thumbnail_url) == (
        "v1",
        "Jisoo & makeup",
        "https://i/m.jpg",
    )
    assert mock.calls[0].url.params["safeSearch"] == "strict"


def test_youtube_errors_raise_upstream_error():
    mock = transport({"/youtube/v3/search": httpx.Response(403)})
    with pytest.raises(UpstreamError):
        anyio.run(YoutubeClient("key", transport=mock).search_videos, "jisoo")
