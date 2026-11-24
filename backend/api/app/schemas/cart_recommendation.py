from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.skincare import StrictModel

type CartMakeupZone = Literal["lip", "blush"]


class CartProduct(StrictModel):
    product_id: str = Field(alias="productId", min_length=1, max_length=64)
    shade_id: str | None = Field(default=None, alias="shadeId", min_length=1, max_length=64)


class CartRecommendationRequest(StrictModel):
    cart_visit_id: UUID = Field(alias="cartVisitId")
    items: list[CartProduct] = Field(min_length=1, max_length=30)
    ar_request_ids: dict[CartMakeupZone, UUID] = Field(default_factory=dict, alias="arRequestIds")


class CartRecommendationCandidate(StrictModel):
    candidate_id: UUID = Field(alias="candidateId")
    product_id: str = Field(alias="productId")
    shade_id: str = Field(alias="shadeId")
    makeup_zone: CartMakeupZone = Field(alias="makeupZone")
    position: int = Field(ge=1, le=5)
    original_rank: int = Field(alias="originalRank", ge=1)
    policy_version: str = Field(alias="policyVersion")
    ar_request_id: UUID | None = Field(default=None, alias="arRequestId")


class CartRecommendations(StrictModel):
    cart_visit_id: UUID = Field(alias="cartVisitId")
    candidates: list[CartRecommendationCandidate] = Field(max_length=5)


class CartRecommendationImpression(StrictModel):
    cart_visit_id: UUID = Field(alias="cartVisitId")
    candidate_id: UUID = Field(alias="candidateId")
    impression_id: UUID = Field(alias="impressionId")
    visibility_policy: Literal["half-visible-500ms-v1", "direct-interaction-v1"] = Field(
        alias="visibilityPolicyVersion"
    )


class CartRecommendationImpressionResult(StrictModel):
    impression_id: UUID = Field(alias="impressionId")


class CartRecommendationAdd(StrictModel):
    event_id: UUID = Field(alias="eventId")
    impression_id: UUID = Field(alias="impressionId")
