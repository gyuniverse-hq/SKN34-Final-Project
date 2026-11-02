from fastapi import APIRouter, Depends, Response

from app.schemas.recommendation import SkinRecommendationRequest, SkinRecommendationResponse
from app.services.recommendation_service import RecommendationService, get_recommendation_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("/skin", response_model=SkinRecommendationResponse)
async def recommend_skin(
    body: SkinRecommendationRequest,
    response: Response,
    service: RecommendationService = Depends(get_recommendation_service),
) -> SkinRecommendationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend(body)
