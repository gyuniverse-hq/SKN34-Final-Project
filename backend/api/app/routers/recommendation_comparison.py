from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, require_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.schemas.recommendation_comparison import ComparisonInput
from app.schemas.recommendation_feedback import (
    RecommendationEventInput,
    RecommendationImpressionInput,
    RecordedComparisonInput,
)
from app.services.recommendation_comparison_service import comparison_service
from app.services.recommendation_feedback_service import feedback_service

router = APIRouter(prefix="/api/dev/recommendations", tags=["recommendation-comparison"])


def enabled():
    settings = get_settings()
    if settings.env not in ("local", "development", "test") or not (
        settings.recommendation_comparison_enabled
    ):
        raise ApiError(404, "Not found", "not_found")


def validate_model_input(body: ComparisonInput):
    if get_settings().recommendation_model == "recommend-cat-v4" and (
        body.analysis_version != "skin-analysis-v4.1" or body.scores.acne is None
    ):
        raise ApiError(
            422, "A v4.1 skin analysis with an acne score is required", "acne_score_required"
        )


@router.post("/compare", dependencies=[Depends(enabled)])
async def compare(
    body: ComparisonInput,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    validate_model_input(body)
    return await comparison_service(session, get_settings()).compare(body)


@router.post("/compare/recorded", dependencies=[Depends(enabled)])
async def recorded_compare(
    body: RecordedComparisonInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    validate_model_input(body.input)
    return await feedback_service(session, get_settings()).compare(body, user.id)


@router.post("/impressions", dependencies=[Depends(enabled)])
async def impression(
    body: RecommendationImpressionInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).impression(body, user.id)


@router.post("/events", dependencies=[Depends(enabled)])
async def event(
    body: RecommendationEventInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await feedback_service(session, get_settings()).event(body, user.id)
