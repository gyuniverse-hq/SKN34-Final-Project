from fastapi import APIRouter, Depends, Query, Response

from app.core.http import cache_for
from app.schemas.shade import ShadeRecommendRequest, ShadeRecommendResponse, SimilarShadesResponse
from app.services.shade_service import ShadeService, get_shade_service

router = APIRouter(prefix="/api/shades", tags=["shades"])


@router.post("/recommend", response_model=ShadeRecommendResponse)
async def recommend(
    body: ShadeRecommendRequest, service: ShadeService = Depends(get_shade_service)
) -> ShadeRecommendResponse:
    return await service.recommend(body)


@router.get("/similar", response_model=SimilarShadesResponse)
async def similar(
    response: Response,
    product_id: str = Query(alias="productId", min_length=1, max_length=64),
    shade_id: str = Query(alias="shadeId", min_length=1, max_length=64),
    limit: int = Query(default=8, ge=1, le=20),
    service: ShadeService = Depends(get_shade_service),
) -> SimilarShadesResponse:
    result = await service.similar(product_id, shade_id, limit)
    cache_for(response, 300)
    return result
