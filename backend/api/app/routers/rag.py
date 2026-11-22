"""Internal G5 endpoints called by the chatbot."""

from secrets import compare_digest

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.schemas.rag import RagContext, RagNeighbors, RagSearch, RagSearchResponse
from app.services.rag_search_service import RagSearchService, create_search_service


def authorized(x_g5_token: str = Header(default="")):
    settings = get_settings()
    if not settings.g5_enabled:
        raise ApiError(404, "Knowledge is unavailable", "g5_disabled")
    token = settings.g5_internal_token
    if not token or not compare_digest(token.encode(), x_g5_token.encode()):
        raise ApiError(403, "Knowledge access denied", "g5_forbidden")


router = APIRouter(prefix="/internal/knowledge", dependencies=[Depends(authorized)])


def use_service(db: AsyncSession = Depends(get_session)):
    return create_search_service(db)


@router.post("/search", response_model=RagSearchResponse)
async def search(payload: RagSearch, service: RagSearchService = Depends(use_service)):
    return await service.search(payload)


@router.post("/context", response_model=list[RagNeighbors])
async def context(payload: RagContext, service: RagSearchService = Depends(use_service)):
    return [await service.context(ref) for ref in payload.evidence]
