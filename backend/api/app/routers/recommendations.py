from fastapi import APIRouter, Depends, Response

from app.core.config import get_settings
from app.schemas.recommendation import SkinRecommendationRequest, SkinRecommendationResponse
from app.schemas.skincare import (
    HybridRequest,
    HybridResponse,
    SkincareProfileRequest,
    SkincareRequest,
    SkincareResponse,
)
from app.services.recommendation_service import RecommendationService, get_recommendation_service
from app.services.skincare_service import SkincareService, get_skincare_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("/skin", response_model=SkinRecommendationResponse)
async def recommend_skin(
    body: SkinRecommendationRequest,
    response: Response,
    service: RecommendationService = Depends(get_recommendation_service),
) -> SkinRecommendationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend(body)


@router.post("/skincare", response_model=SkincareResponse, response_model_exclude_none=True)
async def recommend_skincare(
    body: SkincareRequest,
    response: Response,
    service: SkincareService = Depends(get_skincare_service),
) -> SkincareResponse:
    response.headers["Cache-Control"] = "no-store"
    trace_allowed = body.include_trace and get_settings().env in ("local", "development", "test")
    return await service.recommend(body, trace_allowed)


@router.post("/skincare/v2", response_model=HybridResponse)
async def recommend_hybrid(
    body: HybridRequest,
    response: Response,
    service: SkincareService = Depends(get_skincare_service),
) -> HybridResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend_hybrid(body)


@router.post("/skincare/v4", response_model=HybridResponse)
async def recommend_automatically(
    body: SkincareProfileRequest,
    response: Response,
    service: SkincareService = Depends(get_skincare_service),
) -> HybridResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend_hybrid(body)
