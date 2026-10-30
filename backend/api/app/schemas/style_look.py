from app.schemas.base import ApiModel, OmitNoneModel


class StyleProduct(OmitNoneModel):
    number: int
    brand: str
    name: str
    option: str
    category: str
    zone: str
    review_status: str
    mapping_verified: bool | None = None
    catalog_product_id: str | None = None
    catalog_shade_id: str | None = None


class StyleLook(ApiModel):
    id: str
    title: str
    group: str
    tag: str
    video_url: str
    products: list[StyleProduct]


class StyleLooksResponse(ApiModel):
    looks: list[StyleLook]
