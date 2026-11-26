from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.schemas.recommendation import SkinRecommendationRequest, SkinRecommendationResponse
from app.schemas.recommendation_feedback import (
    RecordedSkincareInput,
    SkincareEventInput,
    SkincareImpressionInput,
)
from app.schemas.skincare import HybridResponse, SkincareProfileRequest
from app.services.recommendation_feedback_service import feedback_service
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


@router.post("/skincare/v4", response_model=HybridResponse)
async def recommend_automatically(
    body: SkincareProfileRequest,
    response: Response,
    service: SkincareService = Depends(get_skincare_service),
) -> HybridResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend_hybrid(body)


@router.post("/skincare/v4/recorded", response_model=HybridResponse)
async def recommend_skincare_recorded(
    body: RecordedSkincareInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    service: SkincareService = Depends(get_skincare_service),
) -> HybridResponse:
    response.headers["Cache-Control"] = "no-store"
    feedback = feedback_service(session, get_settings())
    return await service.recommend_recorded(body, user.id, feedback)


@router.post("/skincare/v4/impressions")
async def skincare_impression(
    body: SkincareImpressionInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).impression(body, user.id)


@router.post("/skincare/v4/events")
async def skincare_event(
    body: SkincareEventInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).event(body, user.id)
