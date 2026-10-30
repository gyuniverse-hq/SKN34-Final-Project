from fastapi import APIRouter, Depends, Response

from app.core.http import cache_for
from app.schemas.style_look import StyleLooksResponse
from app.services.style_look_service import StyleLookService, get_style_look_service

router = APIRouter(prefix="/api/style-looks", tags=["style-looks"])


@router.get("", response_model=StyleLooksResponse)
async def list_style_looks(
    response: Response, service: StyleLookService = Depends(get_style_look_service)
) -> StyleLooksResponse:
    looks = await service.list_looks()
    cache_for(response, 300)
    return StyleLooksResponse(looks=looks)
