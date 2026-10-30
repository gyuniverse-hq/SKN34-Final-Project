from typing import Literal

from app.schemas.base import ApiModel


class CelebrityVideoProduct(ApiModel):
    number: int
    category: str
    zone: str
    brand: str
    name: str
    option: str
    review_status: str
    source_type: str


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
