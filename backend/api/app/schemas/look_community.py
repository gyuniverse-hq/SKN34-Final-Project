from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.base import ApiModel

CatalogId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,96}$")]


class LookPostProduct(ApiModel):
    product_id: CatalogId
    shade_id: CatalogId | None = None


class LookPostContent(ApiModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    products: list[LookPostProduct] = Field(default_factory=list, max_length=12)


class LookPost(LookPostContent):
    id: UUID
    created_at: datetime
    votes: int
    hidden: bool


class LookPostReport(ApiModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class LookPostViewer(ApiModel):
    owned: bool
    recommended: bool
    reported: bool


class ReportedLookPost(LookPost):
    reasons: list[str]


class LookPostModeration(ApiModel):
    hidden: bool
