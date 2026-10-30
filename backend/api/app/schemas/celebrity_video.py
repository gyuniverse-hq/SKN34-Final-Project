from typing import Literal

from app.schemas.base import ApiModel, OmitNoneModel


class CelebrityVideoProduct(OmitNoneModel):
    number: int
    category: str
    zone: str
    brand: str
    name: str
    option: str
    review_status: str
    source_type: str
    mapping_verified: bool | None = None
    catalog_product_id: str | None = None
    catalog_shade_id: str | None = None


class CelebrityVideo(ApiModel):
    id: str
    celebrity_id: str
    number: int
    start_seconds: int
    link_status: Literal["metadata_available", "needs_review"]
    title: str
    channel_name: str
    products: list[CelebrityVideoProduct]


class CelebrityVideosResponse(ApiModel):
    videos: list[CelebrityVideo]
