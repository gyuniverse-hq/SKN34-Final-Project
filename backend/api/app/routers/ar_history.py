from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, require_user
from app.schemas.ar_history import (
    Activity,
    Impression,
    PaletteInputs,
    PaletteRequest,
    PaletteZone,
    RankedPalette,
    RankPalette,
)
from app.services.ar_history_service import ArHistoryService, get_ar_history

router = APIRouter(prefix="/api/me/ar-history", tags=["AR activity"])


@router.post("/status")
async def status(
    user: AuthUser = Depends(require_user), service: ArHistoryService = Depends(get_ar_history)
):
    enabled, recommendations = await service.access(user.id)
    result = {"enabled": enabled, "recommendations": recommendations}
    if recommendations and service.ranking_enabled():
        result["serverRanking"] = True
    return result


@router.post("/rank", response_model=RankedPalette)
async def rank(
    body: RankPalette,
    user: AuthUser = Depends(require_user),
    service: ArHistoryService = Depends(get_ar_history),
) -> RankedPalette:
    return await service.rank(user.id, body)


@router.post("/requests")
async def requests(
    body: PaletteRequest,
    user: AuthUser = Depends(require_user),
    service: ArHistoryService = Depends(get_ar_history),
):
    await service.record(user.id, body)
    return {"ok": True}


@router.post("/palette", response_model=PaletteInputs)
async def palette(
    body: PaletteZone,
    user: AuthUser = Depends(require_user),
    service: ArHistoryService = Depends(get_ar_history),
) -> PaletteInputs:
    return await service.palette(user.id, body.makeup_zone)


@router.post("/impressions")
async def impressions(
    body: Impression,
    user: AuthUser = Depends(require_user),
    service: ArHistoryService = Depends(get_ar_history),
):
    await service.record(user.id, body)
    return {"ok": True}


@router.post("/events")
async def events(
    body: Activity,
    user: AuthUser = Depends(require_user),
    service: ArHistoryService = Depends(get_ar_history),
):
    await service.record(user.id, body)
    return {"ok": True}
