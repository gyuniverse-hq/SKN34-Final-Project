from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.schemas.recommendation_comparison import ComparisonInput
from app.services.recommendation_comparison_service import comparison_service

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
