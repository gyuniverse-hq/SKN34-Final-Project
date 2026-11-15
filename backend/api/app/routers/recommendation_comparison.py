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


@router.post("/compare", dependencies=[Depends(enabled)])
async def compare(
    body: ComparisonInput,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await comparison_service(session, get_settings()).compare(body)


@router.post("/compare/recorded", dependencies=[Depends(enabled)])
async def recorded_compare(
    body: RecordedComparisonInput,
    response: Response,
    user: AuthUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
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
