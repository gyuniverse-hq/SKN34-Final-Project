from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.schemas.recommendation import SkinRecommendationRequest, SkinRecommendationResponse
from app.schemas.recommendation_comparison import ComparisonInput, SkinV2Response
from app.schemas.recommendation_feedback import (
    RecommendationEventInput,
    RecommendationImpressionInput,
    RecordedComparisonInput,
)
from app.schemas.skincare import (
    HybridRequest,
    HybridResponse,
    SkincareProfileRequest,
    SkincareRequest,
    SkincareResponse,
)
from app.services.recommendation_feedback_service import feedback_service
from app.services.recommendation_service import RecommendationService, get_recommendation_service
from app.services.skin_v2_service import SkinV2Service, get_skin_v2_service
from app.services.skincare_service import SkincareService, get_skincare_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("/skin-v2", response_model=SkinV2Response, response_model_exclude_unset=True)
async def recommend_skin_v2(
    body: ComparisonInput,
    response: Response,
    service: SkinV2Service = Depends(get_skin_v2_service),
):
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend(body)


@router.post("/skin-v2/recorded", response_model=SkinV2Response, response_model_exclude_unset=True)
async def recommend_skin_v2_recorded(
    body: RecordedComparisonInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    service: SkinV2Service = Depends(get_skin_v2_service),
):
    response.headers["Cache-Control"] = "no-store"
    return await service.recommend(body.input, member_id=user.id, session_id=body.session_id)


@router.post("/skin-v2/impressions")
async def skin_v2_impression(
    body: RecommendationImpressionInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).impression(body, user.id, serving=True)


@router.post("/skin-v2/events")
async def skin_v2_event(
    body: RecommendationEventInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).event(body, user.id, serving=True)


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
