from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.catalog import MakeupState, MakeupZone, Product

VideoAnalysisStatus = Literal['registered', 'metadata_unavailable', 'metadata_ready']
ProductMappingStatus = Literal['unreviewed', 'no_verified_products', 'mapped']
LookProductStatus = Literal['verified_used', 'unverified', 'similar']


class IdolVideo(ApiModel):
    id: str
    video_id: str
    youtube_url: str
    start_seconds: int = Field(ge=0)
    title: str
    channel_name: str
    thumbnail_url: str
    description: str | None = None
    published_at: str | None = None
    makeup_look_id: str
    analysis_status: VideoAnalysisStatus
    product_mapping_status: ProductMappingStatus


class IdolLookProduct(ApiModel):
    id: str
    makeup_zone: MakeupZone
    status: LookProductStatus
    product_id: str | None = None
    shade_id: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    evidence_text: str | None = None
    verified: bool
    similarity_score: float | None = Field(default=None, ge=0, le=1)
    recommendation_reason: str | None = None


class IdolLook(ApiModel):
    id: str
    display_name: str
    style_description: str
    is_published: bool
    video: IdolVideo
    products: list[IdolLookProduct]
    ar_settings: MakeupState


class IdolLooksResponse(ApiModel):
    looks: list[IdolLook]


class IdolLookDetailResponse(ApiModel):
    look: IdolLook
    products: list[Product]
