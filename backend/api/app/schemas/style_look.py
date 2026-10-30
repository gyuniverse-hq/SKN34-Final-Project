from app.schemas.base import ApiModel


class StyleProduct(ApiModel):
    number: int
    brand: str
    name: str
    option: str
    category: str
    zone: str
    review_status: str


class StyleLook(ApiModel):
    id: str
    title: str
    group: str
    tag: str
    video_url: str
    products: list[StyleProduct]


class StyleLooksResponse(ApiModel):
    looks: list[StyleLook]
