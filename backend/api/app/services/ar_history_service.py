from datetime import UTC, datetime, timedelta

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.ar_history_repository import ArHistoryRepository
from app.schemas.ar_history import Activity, Impression, PaletteInputs, PaletteRequest
from app.services.ar_palette_service import ArPaletteService
from app.services.member_service import TERMS_VERSION


class ArHistoryService:
    def __init__(self, repo: ArHistoryRepository):
        self.repo = repo

    async def enabled(self, owner: str) -> bool:
        return (
            owner in get_settings().ar_activity_consented_members
            and await self.repo.member_terms(owner) == TERMS_VERSION
        )

    async def recommended(self, owner: str) -> bool:
        return owner in get_settings().ar_activity_enrolled_members and await self.enabled(owner)

    async def require_enabled(self, owner: str):
        if not await self.enabled(owner):
            raise ApiError(403, "AR activity collection is disabled", "ar_history_disabled")

    async def palette(self, owner: str, zone: str) -> PaletteInputs:
        if not await self.recommended(owner):
            raise ApiError(403, "Subscription required", "ar_recommendation_disabled")
        return await self.repo.palette_inputs(owner, zone)

    @staticmethod
    def ranking_enabled():
        return get_settings().ar_palette_mode != "legacy"

    async def rank(self, owner, body):
        if not self.ranking_enabled():
            raise ApiError(404, "AR server ranking is disabled", "ar_ranking_disabled")
        if not await self.recommended(owner):
            raise ApiError(403, "Subscription required", "ar_recommendation_disabled")
        return await ArPaletteService(self.repo, get_settings()).rank(owner, body)

    async def record(self, owner: str, body: PaletteRequest | Impression | Activity):
        await self.require_enabled(owner)
        if isinstance(body, PaletteRequest):
            if not await self.recommended(owner):
                raise ApiError(403, "Subscription required", "ar_recommendation_disabled")
            await self.repo.request(owner, body)
            return
        now = datetime.now(UTC)
        if not now - timedelta(days=1) <= body.occurred_at <= now + timedelta(minutes=5):
            raise ApiError(400, "Invalid AR occurrence time", "invalid_ar_time")
        if isinstance(body, Impression):
            if not await self.recommended(owner):
                raise ApiError(403, "Subscription required", "ar_recommendation_disabled")
            await self.repo.impression(owner, body)
        else:
            if body.impression_id and not await self.recommended(owner):
                raise ApiError(403, "Subscription required", "ar_recommendation_disabled")
            await self.repo.event(owner, body)


def get_ar_history(session: AsyncSession = Depends(get_session)) -> ArHistoryService:
    return ArHistoryService(ArHistoryRepository(session))
