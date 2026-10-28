import anyio
import httpx
import pytest

from app.clients.naver_client import NaverClient, clean_text, to_https_shopping_image
from app.clients.youtube_client import YoutubeClient, youtube_duration_seconds
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


def test_youtube_metadata_is_parsed_and_unescapes_text():
    payload = {
        "items": [
            {
                "snippet": {
                    "title": "Rosy &amp; soft",
                    "channelTitle": "JIYU &amp; Team",
                    "publishedAt": "2026-10-01T00:00:00Z",
                    "description": "Official description",
                    "thumbnails": {"high": {"url": "https://i/high.jpg"}},
                }
            }
        ]
    }
    mock = transport({"/youtube/v3/videos": httpx.Response(200, json=payload)})
    metadata = anyio.run(YoutubeClient("key", transport=mock).get_video_metadata, "video-1")
    assert metadata is not None
    assert metadata.title == "Rosy & soft"
    assert metadata.channel_title == "JIYU & Team"
    assert metadata.thumbnail_url == "https://i/high.jpg"
    assert metadata.description == "Official description"


def test_youtube_metadata_without_key_makes_no_request():
    mock = transport({})
    client = YoutubeClient(None, transport=mock)
    assert anyio.run(client.get_video_metadata, "video-1") is None
    assert mock.calls == []


def test_youtube_playlist_follows_all_pages_and_preserves_positions():
    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("pageToken")
        if token == "next":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "item-2",
                            "snippet": {
                                "position": 1,
                                "title": "Second",
                                "videoOwnerChannelTitle": "Channel",
                                "publishedAt": "2026-02-01",
                            },
                            "contentDetails": {"videoId": "v2"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "nextPageToken": "next",
                "items": [
                    {
                        "id": "item-1",
                        "snippet": {
                            "position": 0,
                            "title": "First",
                            "videoOwnerChannelTitle": "Channel",
                            "publishedAt": "2026-01-01",
                        },
                        "contentDetails": {"videoId": "v1"},
                    }
                ],
            },
        )

    mock = httpx.MockTransport(handler)
    items = anyio.run(YoutubeClient("key", transport=mock).list_playlist_items, "playlist-1")
    assert [(item.position, item.video_id) for item in items] == [(0, "v1"), (1, "v2")]


def test_youtube_video_details_include_status_and_duration():
    payload = {
        "items": [
            {
                "id": "v1",
                "snippet": {
                    "title": "Makeup",
                    "channelTitle": "Channel",
                    "description": "Description",
                    "publishedAt": "2026-01-01",
                    "thumbnails": {"maxres": {"url": "https://i/max.jpg"}},
                },
                "status": {"privacyStatus": "public", "embeddable": True},
                "contentDetails": {"duration": "PT1H2M3S"},
            }
        ]
    }
    mock = transport({"/youtube/v3/videos": httpx.Response(200, json=payload)})
    [video] = anyio.run(YoutubeClient("key", transport=mock).get_video_details, ["v1"])
    assert video.duration_iso8601 == "PT1H2M3S"
    assert video.duration_seconds == 3723
    assert video.embeddable
    assert video.privacy_status == "public"
    assert video.thumbnail_url == "https://i/max.jpg"
    assert youtube_duration_seconds("P1DT2M3S") == 86523
