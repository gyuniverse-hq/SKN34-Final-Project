from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.catalog import MakeupZone, Product

Undertone = Literal["cool", "neutral", "warm"]
SimilarReason = Literal["close_color", "same_texture", "same_category"]


class SkinTone(ApiModel):
    """On-device estimate only. Face video and images never reach the server."""

    ita: float | None = Field(default=None, ge=-90, le=90, description="Individual Typology Angle")
    mst: int = Field(ge=1, le=10, description="Monk Skin Tone scale level")
    undertone: Undertone = "neutral"


class ShadeRecommendRequest(ApiModel):
    skin: SkinTone
    limit: int = Field(default=5, ge=1, le=20)


class ShadeMatch(ApiModel):
    product_id: str
    shade_id: str
    brand: str
    product_name: str
    shade_name: str
    hex: str
    delta_e: float


class ShadeRecommendResponse(ApiModel):
    skin_hex: str
    matches: list[ShadeMatch]


class SimilarSource(ApiModel):
    product_id: str
    shade_id: str
    hex: str
    makeup_zone: MakeupZone


class SimilarShadeMatch(ApiModel):
    product_id: str
    shade_id: str
    delta_e: float
    reasons: list[SimilarReason]


class SimilarShadesResponse(ApiModel):
    """Official shade colors only; AR intensity and lighting are not part of the ranking."""

    source: SimilarSource
    matches: list[SimilarShadeMatch]
    products: list[Product]
