from typing import Literal

from app.schemas.base import ApiModel, OmitNoneModel


class ProductVideo(OmitNoneModel):
    source: Literal["celebrity", "style"]
    id: str
    title: str
    channel_name: str
    celebrity_id: str | None = None
    shade_id: str | None = None


class ProductVideosResponse(ApiModel):
    videos: list[ProductVideo]
