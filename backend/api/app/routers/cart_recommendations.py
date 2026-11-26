from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, require_user
from app.schemas.cart_recommendation import (
    CartRecommendationAdd,
    CartRecommendationImpression,
    CartRecommendationImpressionResult,
    CartRecommendationRequest,
    CartRecommendations,
)
from app.services.cart_recommendation_service import (
    CartRecommendationService,
    get_cart_recommendations,
)

router = APIRouter(prefix="/api/me/cart-recommendations", tags=["Cart recommendations"])


@router.post("", response_model=CartRecommendations | None)
async def visit(
    body: CartRecommendationRequest,
    user: AuthUser = Depends(require_user),
    service: CartRecommendationService = Depends(get_cart_recommendations),
):
    return await service.visit(user.id, body)


@router.post("/impressions", response_model=CartRecommendationImpressionResult)
async def impression(
    body: CartRecommendationImpression,
    user: AuthUser = Depends(require_user),
    service: CartRecommendationService = Depends(get_cart_recommendations),
):
    return CartRecommendationImpressionResult(impression_id=await service.impression(user.id, body))


@router.post("/cart-adds")
async def cart_add(
    body: CartRecommendationAdd,
    user: AuthUser = Depends(require_user),
    service: CartRecommendationService = Depends(get_cart_recommendations),
):
    await service.cart_add(user.id, body)
    return {"ok": True}
