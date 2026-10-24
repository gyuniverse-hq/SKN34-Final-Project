from pydantic import Field

from app.schemas.base import ApiModel


class ShoppingOffer(ApiModel):
    title: str
    mall_name: str
    price_krw: int = Field(alias="priceKRW")
    image_url: str
    link: str


class ProductOffers(ApiModel):
    configured: bool
    offers: list[ShoppingOffer]


class YoutubeVideo(ApiModel):
    video_id: str
    title: str
    channel_title: str
    thumbnail_url: str
    published_at: str


class YoutubeSearchResult(ApiModel):
    configured: bool
    videos: list[YoutubeVideo]


class Integrations(ApiModel):
    youtube: bool
    naver_shopping: bool


class HealthResponse(ApiModel):
    ok: bool
    integrations: Integrations
