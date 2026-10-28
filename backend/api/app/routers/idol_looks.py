from fastapi import APIRouter, Depends, Response

from app.core.errors import ApiError
from app.core.http import cache_for
from app.schemas.idol_look import IdolLookDetailResponse, IdolLooksResponse
from app.services.idol_look_service import IdolLookService, get_idol_look_service

router = APIRouter(prefix="/api/idol-looks", tags=["idol-looks"])


@router.get("", response_model=IdolLooksResponse)
async def list_idol_looks(
    response: Response, service: IdolLookService = Depends(get_idol_look_service)
):
    cache_for(response, 300)
    return IdolLooksResponse(looks=await service.list_looks())


@router.get("/{look_id}", response_model=IdolLookDetailResponse)
async def get_idol_look(
    look_id: str, response: Response, service: IdolLookService = Depends(get_idol_look_service)
):
    result = await service.detail(look_id)
    if result is None:
        raise ApiError(404, "Idol look not found", "not_found")
    look, products = result
    cache_for(response, 300)
    return IdolLookDetailResponse(look=look, products=products)
