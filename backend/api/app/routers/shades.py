from fastapi import APIRouter, Depends

from app.schemas.shade import ShadeRecommendRequest, ShadeRecommendResponse
from app.services.shade_service import ShadeService, get_shade_service

router = APIRouter(prefix="/api/shades", tags=["shades"])


@router.post("/recommend", response_model=ShadeRecommendResponse)
async def recommend(
    body: ShadeRecommendRequest, service: ShadeService = Depends(get_shade_service)
) -> ShadeRecommendResponse:
    return await service.recommend(body)
