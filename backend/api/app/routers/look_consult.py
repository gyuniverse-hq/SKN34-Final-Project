from fastapi import APIRouter, Depends, Query

from app.core.errors import ApiError
from app.schemas.look_consult import LookVideoTagsResponse, TroubleshootingResponse
from app.services.look_consult_service import LookConsultService, get_look_consult_service

router = APIRouter(prefix="/api/look-consult", tags=["look-consult"])

MAX_IDS = 200


@router.get("/makeup-troubleshooting", response_model=TroubleshootingResponse)
async def list_makeup_troubleshooting(
    category: str | None = Query(default=None, max_length=40),
    problem_id: str | None = Query(default=None, alias="problemId", max_length=20),
    service: LookConsultService = Depends(get_look_consult_service),
) -> TroubleshootingResponse:
    """Approved general makeup advice only (makeup_troubleshooting_serving)."""
    return TroubleshootingResponse(advice=await service.troubleshooting(category, problem_id))


@router.get("/look-tags", response_model=LookVideoTagsResponse)
async def list_look_tags(
    ids: list[str] = Query(default=[], alias="id"),
    service: LookConsultService = Depends(get_look_consult_service),
) -> LookVideoTagsResponse:
    """Tags by VIDEO-xxx, YouTube id or LOOK-xxx (repeat `id`); all look videos when omitted."""
    if len(ids) > MAX_IDS or any(not item or len(item) > 64 for item in ids):
        raise ApiError(
            422, f"Pass 1 to 64 characters per id and at most {MAX_IDS} ids", "invalid_id"
        )
    return LookVideoTagsResponse(tags=await service.look_tags(ids))
